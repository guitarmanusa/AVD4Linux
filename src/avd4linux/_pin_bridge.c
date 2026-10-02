#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <dlfcn.h>
#include <string.h>

#define WEBKIT_CREDENTIAL_PERSISTENCE_NONE 0

typedef const char* (*fn_gtk_editable_get_text)(void *editable);
typedef void (*fn_gtk_editable_delete_text)(void *editable, int start_pos, int end_pos);
typedef void* (*fn_webkit_credential_new_for_certificate_pin)(const char *pin, int persistence);
typedef void (*fn_webkit_authentication_request_authenticate)(void *request, void *credential);
typedef void (*fn_webkit_authentication_request_cancel)(void *request);
typedef void (*fn_webkit_credential_free)(void *credential);
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

    if (!PyArg_ParseTuple(args, "OO", &entry_obj, &request_obj)) {
        return NULL;
    }

    void *entry_ptr = extract_gpointer(entry_obj);
    void *request_ptr = extract_gpointer(request_obj);

    if (!entry_ptr || !request_ptr) {
        PyErr_SetString(PyExc_ValueError, "Invalid GObject pointers for entry or request");
        return NULL;
    }

    /* Resolve runtime symbols from already-loaded GTK4/3 and WebKitGTK libraries */
    fn_gtk_editable_get_text p_gtk_editable_get_text =
        (fn_gtk_editable_get_text)dlsym(RTLD_DEFAULT, "gtk_editable_get_text");
    if (!p_gtk_editable_get_text) {
        p_gtk_editable_get_text = (fn_gtk_editable_get_text)dlsym(RTLD_DEFAULT, "gtk_entry_get_text");
    }
    fn_gtk_editable_delete_text p_gtk_editable_delete_text =
        (fn_gtk_editable_delete_text)dlsym(RTLD_DEFAULT, "gtk_editable_delete_text");
    fn_webkit_credential_new_for_certificate_pin p_webkit_credential_new_for_certificate_pin =
        (fn_webkit_credential_new_for_certificate_pin)dlsym(RTLD_DEFAULT, "webkit_credential_new_for_certificate_pin");
    fn_webkit_authentication_request_authenticate p_webkit_authentication_request_authenticate =
        (fn_webkit_authentication_request_authenticate)dlsym(RTLD_DEFAULT, "webkit_authentication_request_authenticate");
    fn_webkit_authentication_request_cancel p_webkit_authentication_request_cancel =
        (fn_webkit_authentication_request_cancel)dlsym(RTLD_DEFAULT, "webkit_authentication_request_cancel");
    fn_webkit_credential_free p_webkit_credential_free =
        (fn_webkit_credential_free)dlsym(RTLD_DEFAULT, "webkit_credential_free");

    if (!p_gtk_editable_get_text || !p_webkit_credential_new_for_certificate_pin ||
        !p_webkit_authentication_request_authenticate) {
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

    /* Clear the entry widget in GTK */
    if (p_gtk_editable_delete_text) {
        p_gtk_editable_delete_text(entry_ptr, 0, -1);
    }

    /* Pass C string directly to WebKit credential constructor with NONE persistence */
    void *cred = p_webkit_credential_new_for_certificate_pin(pin_buf, WEBKIT_CREDENTIAL_PERSISTENCE_NONE);

    /* Cryptographically erase the stack buffer immediately */
    secure_cleanse(pin_buf, sizeof(pin_buf));

    if (!cred) {
        if (p_webkit_authentication_request_cancel) {
            p_webkit_authentication_request_cancel(request_ptr);
        }
        Py_RETURN_FALSE;
    }

    /* Submit credential to WebKit authentication request */
    p_webkit_authentication_request_authenticate(request_ptr, cred);

    /* Free credential structure */
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
