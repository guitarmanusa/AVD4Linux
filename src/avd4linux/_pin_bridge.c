#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <dlfcn.h>
#include <string.h>

#define WEBKIT_CREDENTIAL_PERSISTENCE_NONE 0
#define WEBKIT_CREDENTIAL_PERSISTENCE_FOR_SESSION 1

typedef const char* (*fn_gtk_editable_get_text)(void *editable);
typedef void* (*fn_g_tls_certificate_new_from_pkcs11_uris)(const char *cert_uri, const char *key_uri, void *error);
typedef void* (*fn_webkit_credential_new_for_certificate)(void *certificate, int persistence);
typedef void* (*fn_webkit_credential_new_for_certificate_pin)(const char *pin, int persistence);
typedef void (*fn_webkit_authentication_request_authenticate)(void *request, void *credential);
typedef void (*fn_webkit_authentication_request_cancel)(void *request);
typedef void (*fn_webkit_credential_free)(void *credential);
typedef void (*fn_g_object_unref)(void *object);
typedef void (*fn_openssl_cleanse)(void *ptr, size_t len);

static void secure_cleanse(void *v, size_t n) {
    if (!v || n == 0) return;

    /* 1. Use OpenSSL's OPENSSL_cleanse() if libcrypto is loaded in the process */
    fn_openssl_cleanse p_cleanse = (fn_openssl_cleanse)dlsym(RTLD_DEFAULT, "OPENSSL_cleanse");
    if (p_cleanse) {
        p_cleanse(v, n);
    }

    /* 2. Standard glibc explicit_bzero to prevent compiler optimization */
#if defined(__GLIBC__) || defined(__linux__)
    explicit_bzero(v, n);
#endif

    /* 3. Volatile write to guarantee memory erasure occurs */
    volatile unsigned char *p = (volatile unsigned char *)v;
    while (n--) {
        *p++ = 0;
    }
}

static void* extract_gpointer(PyObject *obj) {
    if (!obj) return NULL;
    PyObject *capsule = PyObject_GetAttrString(obj, "__gpointer__");
    if (!capsule) {
        PyErr_Clear();
        return NULL;
    }
    if (!PyCapsule_CheckExact(capsule)) {
        Py_DECREF(capsule);
        return NULL;
    }
    void *ptr = PyCapsule_GetPointer(capsule, NULL);
    Py_DECREF(capsule);
    return ptr;
}

static PyObject* py_authenticate_pin(PyObject *self, PyObject *args) {
    PyObject *entry_obj = NULL;
    PyObject *request_obj = NULL;
    const char *cert_uri = NULL;
    const char *key_uri = NULL;

    if (!PyArg_ParseTuple(args, "OO|zz", &entry_obj, &request_obj, &cert_uri, &key_uri)) {
        return NULL;
    }

    void *entry_ptr = extract_gpointer(entry_obj);
    void *request_ptr = extract_gpointer(request_obj);

    if (!entry_ptr || !request_ptr) {
        PyErr_SetString(PyExc_ValueError, "Invalid GObject pointers for entry or request");
        return NULL;
    }

    /* Resolve runtime symbols from already-loaded GTK4/3, GIO and WebKitGTK libraries */
    fn_gtk_editable_get_text p_gtk_editable_get_text =
        (fn_gtk_editable_get_text)dlsym(RTLD_DEFAULT, "gtk_editable_get_text");
    if (!p_gtk_editable_get_text) {
        p_gtk_editable_get_text = (fn_gtk_editable_get_text)dlsym(RTLD_DEFAULT, "gtk_entry_get_text");
    }
    fn_g_tls_certificate_new_from_pkcs11_uris p_g_tls_certificate_new_from_pkcs11_uris =
        (fn_g_tls_certificate_new_from_pkcs11_uris)dlsym(RTLD_DEFAULT, "g_tls_certificate_new_from_pkcs11_uris");
    fn_webkit_credential_new_for_certificate p_webkit_credential_new_for_certificate =
        (fn_webkit_credential_new_for_certificate)dlsym(RTLD_DEFAULT, "webkit_credential_new_for_certificate");
    fn_webkit_credential_new_for_certificate_pin p_webkit_credential_new_for_certificate_pin =
        (fn_webkit_credential_new_for_certificate_pin)dlsym(RTLD_DEFAULT, "webkit_credential_new_for_certificate_pin");
    fn_webkit_authentication_request_authenticate p_webkit_authentication_request_authenticate =
        (fn_webkit_authentication_request_authenticate)dlsym(RTLD_DEFAULT, "webkit_authentication_request_authenticate");
    fn_webkit_authentication_request_cancel p_webkit_authentication_request_cancel =
        (fn_webkit_authentication_request_cancel)dlsym(RTLD_DEFAULT, "webkit_authentication_request_cancel");
    fn_webkit_credential_free p_webkit_credential_free =
        (fn_webkit_credential_free)dlsym(RTLD_DEFAULT, "webkit_credential_free");
    fn_g_object_unref p_g_object_unref =
        (fn_g_object_unref)dlsym(RTLD_DEFAULT, "g_object_unref");

    if (!p_gtk_editable_get_text || !p_webkit_authentication_request_authenticate) {
        PyErr_SetString(PyExc_RuntimeError, "Could not resolve GTK4 or WebKitGTK symbols from process");
        return NULL;
    }

    /* Retrieve text in C without converting to a Python string object */
    const char *raw_pin = p_gtk_editable_get_text(entry_ptr);
    if (!raw_pin || raw_pin[0] == '\0') {
        if (p_webkit_authentication_request_cancel) {
            p_webkit_authentication_request_cancel(request_ptr);
        }
        Py_RETURN_FALSE;
    }

    /* Copy into stack buffer for cryptographic zeroing */
    char pin_buf[256];
    size_t pin_len = strlen(raw_pin);
    if (pin_len >= sizeof(pin_buf)) {
        pin_len = sizeof(pin_buf) - 1;
    }
    memcpy(pin_buf, raw_pin, pin_len);
    pin_buf[pin_len] = '\0';

    void *cred = NULL;

    /* If cert_uri and key_uri are available, embed pin-value into the key URI directly in C memory.
     * This ensures GnuTLS imports the private key already unlocked, avoiding key handle (0x0)
     * invalidation issues during client certificate signature verification. */
    if (cert_uri && cert_uri[0] != '\0' && key_uri && key_uri[0] != '\0' &&
        p_g_tls_certificate_new_from_pkcs11_uris && p_webkit_credential_new_for_certificate) {
        char full_key_uri[1024];
        snprintf(full_key_uri, sizeof(full_key_uri), "%s;pin-value=%s", key_uri, pin_buf);

        void *tls_cert = p_g_tls_certificate_new_from_pkcs11_uris(cert_uri, full_key_uri, NULL);
        secure_cleanse(full_key_uri, sizeof(full_key_uri));

        if (tls_cert) {
            fprintf(stderr, "[PIN_BRIDGE] Bound PIN directly to PKCS#11 key URI in C memory (Zero Python Heap Exposure)\n");
            cred = p_webkit_credential_new_for_certificate(tls_cert, WEBKIT_CREDENTIAL_PERSISTENCE_FOR_SESSION);
            if (p_g_object_unref) {
                p_g_object_unref(tls_cert);
            }
        }
    }

    /* Fallback: standard certificate pin credential */
    if (!cred && p_webkit_credential_new_for_certificate_pin) {
        fprintf(stderr, "[PIN_BRIDGE] Submitting WebKit credential for certificate pin (PIN length: %zu)\n", pin_len);
        cred = p_webkit_credential_new_for_certificate_pin(pin_buf, WEBKIT_CREDENTIAL_PERSISTENCE_FOR_SESSION);
    }

    /* Cryptographically erase the PIN stack buffer immediately */
    secure_cleanse(pin_buf, sizeof(pin_buf));

    if (!cred) {
        if (p_webkit_authentication_request_cancel) {
            p_webkit_authentication_request_cancel(request_ptr);
        }
        Py_RETURN_FALSE;
    }

    /* Submit credential to WebKit authentication request (WebKit manages credential lifecycle) */
    p_webkit_authentication_request_authenticate(request_ptr, cred);

    /* Free credential wrapper in C (WebKit copies WebCore::Credential during authenticate) */
    if (p_webkit_credential_free) {
        p_webkit_credential_free(cred);
    }

    Py_RETURN_TRUE;
}

static PyMethodDef PinBridgeMethods[] = {
    {"authenticate_pin", py_authenticate_pin, METH_VARARGS,
     "Authenticate WebKit request using GTK entry text directly in C memory without Python heap exposure."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef pinbridgemodule = {
    PyModuleDef_HEAD_INIT,
    "_pin_bridge",
    "C extension bridge for zero-Python-heap Smart Card PIN authentication.",
    -1,
    PinBridgeMethods
};

PyMODINIT_FUNC PyInit__pin_bridge(void) {
    return PyModule_Create(&pinbridgemodule);
}
