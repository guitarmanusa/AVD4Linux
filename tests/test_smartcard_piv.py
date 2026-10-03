"""Tests for PIV Authentication certificate discovery.

Regression cover for selecting a *system trust store* root certificate whose
object ID merely starts with 0x01 instead of the CAC's PIV Authentication
certificate, which has object ID exactly 0x01.
"""

import subprocess
import unittest
from unittest import mock

from avd4linux import smartcard
from avd4linux.smartcard import (
    PIV_AUTH_OBJECT_ID,
    _parse_p11tool_certificates,
    _uri_is_hardware_token,
    _uri_object_id,
    get_piv_certificate_uri,
    get_piv_private_key_uri,
)

# The exact URI from the production failure: a Spanish AEAT root CA living in the
# p11-kit-trust module. Its ID starts with 01, so `id=%01` matches it.
TRUST_STORE_ROOT = (
    "pkcs11:model=p11-kit-trust;manufacturer=PKCS%2311%20Kit;serial=1;"
    "token=System%20Trust;id=%01%B9%2F%EF%BF%11%86%60%F2%4F%D0%41%6E%AB%73%1F%E7%D2%6E%49;"
    "object=AC%20RAIZ%20FNMT-RCM%20SERVIDORES%20SEGUROS;type=cert"
)

CAC_PIV_URI = (
    "pkcs11:token=PIV%20II;model=PKCS%2315%20emulated;serial=01;id=%01;"
    "object=PIV%20AUTH%20cert;type=cert"
)

TRUST_STORE_LISTING = """\
Certificate:
  Label: AC RAIZ FNMT-RCM SERVIDORES SEGUROS
  Type: Public Key
  ID: 01b9efbf118660f24fd0416eab731fe7d26e49
  Subject: CN=AC RAIZ FNMT-RCM SERVIDORES SEGUROS,OU=Entidad,...
  Issuer: CN=AC RAIZ FNMT-RCM SERVIDORES SEGUROS,OU=Entidad,...
  Not Before: Fri Sep 15 12:42:55 2007
  Not After : Wed Dec 31 12:42:55 2036
  Usage: Key Cert Sign, CRL Sign
  URL: pkcs11:model=p11-kit-trust;manufacturer=PKCS%2311%20Kit;serial=1;\
token=System%20Trust;id=%01%B9%2F%EF%BF%11%86%60%F2%4F%D0%41%6E%AB%73%1F%E7%D2%6E%49;\
object=AC%20RAIZ%20FNMT-RCM%20SERVIDORES%20SEGUROS;type=cert
"""

CAC_LISTING = """\
Certificate:
  Label: DoD CAC
  Type: Public Key
  ID: 01
  Subject: CN=DoD CAC,...
  Usage: Digital Signature, Key Encipherment, Data Encipherment
  URL: pkcs11:model=PKCS%2315%20emulated;manufacturer=id%3A00000000;serial=01;\
id=%01;object=CAC%20Authentication;type=cert

Certificate:
  Label: PIV Authentication
  Type: Public Key
  ID: 01
  Subject: CN=PIV Authentication SU,...
  Usage: Digital Signature
  URL: pkcs11:token=PIV%20II;model=PKCS%2315%20emulated;serial=01;id=%01;\
object=PIV%20AUTH%20cert;type=cert
"""


def _run(stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


class TestUriHelpers(unittest.TestCase):
    def test_object_id_normalised(self):
        self.assertEqual(_uri_object_id(CAC_PIV_URI), PIV_AUTH_OBJECT_ID)
        # Decodes to 01 B9 2F EF BF 11 86 60 ... -- i.e. it *starts* with 01, which
        # is exactly why `id=%01` used to match it.
        self.assertEqual(
            _uri_object_id(TRUST_STORE_ROOT),
            "01B92FEFBF118660F24FD0416EAB731FE7D26E49",
        )
        self.assertNotEqual(_uri_object_id(TRUST_STORE_ROOT), PIV_AUTH_OBJECT_ID)

    def test_object_id_missing(self):
        self.assertEqual(_uri_object_id("pkcs11:token=x;type=cert"), "")

    def test_trust_store_uri_rejected(self):
        self.assertFalse(_uri_is_hardware_token(TRUST_STORE_ROOT))

    def test_hardware_token_uri_accepted(self):
        self.assertTrue(_uri_is_hardware_token(CAC_PIV_URI))


class TestParseP11ToolOutput(unittest.TestCase):
    def test_each_url_stays_with_its_own_object(self):
        records = _parse_p11tool_certificates(CAC_LISTING)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["label"], "DoD CAC")
        self.assertIn("object=CAC%20Authentication", records[0]["url"])
        self.assertEqual(records[1]["label"], "PIV Authentication")
        self.assertEqual(records[1]["url"], CAC_PIV_URI)

    def test_records_require_a_url(self):
        records = _parse_p11tool_certificates(
            "Certificate:\n  Label: Broken\n  ID: 01\n"
        )
        self.assertEqual(records, [])


class TestPivCertificateUri(unittest.TestCase):
    def _patches(self, stdout: str):
        return (
            mock.patch("shutil.which", return_value="/usr/bin/p11tool"),
            mock.patch("subprocess.run", return_value=_run(stdout)),
        )

    def test_trust_store_root_is_never_selected(self):
        which_patch, run_patch = self._patches(TRUST_STORE_LISTING)
        with which_patch, run_patch:
            self.assertIsNone(get_piv_certificate_uri())

    def test_hardware_piv_certificate_selected(self):
        which_patch, run_patch = self._patches(CAC_LISTING)
        with which_patch, run_patch:
            # Both objects share ID 01; the PIV Authentication one must win.
            self.assertEqual(get_piv_certificate_uri(), CAC_PIV_URI)

    def test_non_piv_slot_9a_object_used_as_fallback(self):
        listing = (
            "Certificate:\n  Label: DoD CAC\n  ID: 01\n"
            "  Usage: Digital Signature, Key Encipherment\n"
            "  URL: pkcs11:model=PKCS%2315%20emulated;serial=01;id=%01;"
            "object=CAC%20Authentication;type=cert\n"
        )
        which_patch, run_patch = self._patches(listing)
        with which_patch, run_patch:
            self.assertEqual(
                get_piv_certificate_uri(),
                "pkcs11:model=PKCS%2315%20emulated;serial=01;id=%01;"
                "object=CAC%20Authentication;type=cert",
            )

    def test_trust_store_listed_first_is_skipped(self):
        combined = TRUST_STORE_LISTING + "\n" + CAC_LISTING
        which_patch, run_patch = self._patches(combined)
        with which_patch, run_patch:
            self.assertEqual(get_piv_certificate_uri(), CAC_PIV_URI)

    def test_longer_id_selected_only_when_labelled_piv(self):
        long_id = (
            "pkcs11:token=PIV%20II;model=PKCS%2315%20emulated;serial=01;"
            "id=%0101;object=PIV%20AUTH%20cert;type=cert"
        )
        listing = (
            "Certificate:\n  Label: Card Authentication\n  ID: 0101\n"
            "  Usage: Digital Signature\n  URL: pkcs11:token=X;id=%01AA;type=cert\n"
            "\n"
            f"Certificate:\n  Label: PIV Authentication\n  ID: 0101\n  URL: {long_id}\n"
        )
        which_patch, run_patch = self._patches(listing)
        with which_patch, run_patch:
            self.assertEqual(get_piv_certificate_uri(), long_id)

    def test_provider_pinned_when_opensc_present(self):
        with mock.patch("shutil.which", return_value="/usr/bin/p11tool"), \
                mock.patch("subprocess.run", return_value=_run(CAC_LISTING)) as run, \
                mock.patch.object(smartcard, "_find_opensc_provider",
                                  return_value="/app/lib/opensc-pkcs11.so"):
            get_piv_certificate_uri()
        first_cmd = run.call_args_list[0].args[0]
        self.assertIn("--provider=/app/lib/opensc-pkcs11.so", first_cmd)

    def test_no_provider_flag_when_opensc_absent(self):
        with mock.patch("shutil.which", return_value="/usr/bin/p11tool"), \
                mock.patch("subprocess.run", return_value=_run(CAC_LISTING)) as run, \
                mock.patch.object(smartcard, "_find_opensc_provider", return_value=None):
            get_piv_certificate_uri()
        first_cmd = run.call_args_list[0].args[0]
        self.assertFalse([a for a in first_cmd if a.startswith("--provider")])

    def test_subprocess_error_does_not_raise(self):
        with mock.patch("shutil.which", return_value="/usr/bin/p11tool"), \
                mock.patch("subprocess.run", side_effect=OSError("boom")):
            self.assertIsNone(get_piv_certificate_uri())

    def test_untrusted_p11tool_path_rejected(self):
        with mock.patch("shutil.which", return_value="/tmp/evil/p11tool"):
            self.assertIsNone(get_piv_certificate_uri())


class TestPivPrivateKeyUri(unittest.TestCase):
    def test_key_uri_reuses_exact_certificate_id(self):
        key_uri = get_piv_private_key_uri(CAC_PIV_URI)
        self.assertEqual(_uri_object_id(key_uri), PIV_AUTH_OBJECT_ID)
        self.assertNotIn("object=", key_uri)
        self.assertIn("type=private", key_uri)

    def test_no_prefix_widening_for_long_ids(self):
        long_id = (
            "pkcs11:token=PIV%20II;model=PKCS%2315%20emulated;serial=01;"
            "id=%0101;object=PIV%20AUTH%20cert;type=cert"
        )
        key_uri = get_piv_private_key_uri(long_id)
        self.assertEqual(_uri_object_id(key_uri), "0101")
        self.assertNotIn("id=%01;", key_uri.replace("id=%0101;", ""))

    def test_key_uri_is_none_without_certificate(self):
        with mock.patch("shutil.which", return_value="/usr/bin/p11tool"), \
                mock.patch("subprocess.run", return_value=_run("")), \
                mock.patch.object(smartcard, "_find_opensc_provider", return_value=None):
            self.assertIsNone(get_piv_private_key_uri(None))


if __name__ == "__main__":
    unittest.main()
