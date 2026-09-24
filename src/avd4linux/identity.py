"""Entra ID Certificate-Based Authentication (CBA) — Linux-native flow.

Mirrors the flow Microsoft's Windows App performs, adapted to Linux:

  1. WebKitGTK/WebKit opens the Entra ID **Certificate Authentication** page
     (`certauth.login.microsoftonline.us` / `certauth.login.microsoftonline.com`).
     WebKit's TLS client-certificate hook terminates mutual TLS using the PIV
     Authentication certificate from the host smartcard (exposed via PKCS#11 / p11-kit).
  2. WebKitGTK keeps a silent background exchange going on the URL known to
     forward to the ARM AVD feed (per-cloud, chosen automatically).
  3. We receive an authorization code via OAuth 2.0 (openid + profile + offline)
     with PKCE, then exchange it for an AVD (WVD/AVD scope) access token + refresh.

This module produces the *exact* HTTP requests Entra ID expects for CBA,
so Phase 2 unit tests can assert every cloud's URL, scope, redirect and
PKCE detail without needing a live tenant.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
import urllib.parse as urlparse
from dataclasses import dataclass, field
from typing import Mapping

from .clouds import CloudProfile, get_cloud

CBA_SUBDOMAIN: Mapping[str, str] = {
    "commercial": "certauth.login.microsoftonline.com",
    "gcc": "certauth.login.microsoftonline.us",
    "dod": "certauth.login.microsoftonline.us",
}

# DoD CA-5x bundle already in the system trust store (verified Phase 1);
# CBA needs only the Entra CBA CA chain which ships with FreeRDP's ARM gateway
# connection set. Scope is the AVD resource for that cloud.
SCOPE_SUFFIX = ".default"


@dataclass
class PKCE:
    verifier: str = field(default_factory=lambda: secrets.token_urlsafe(64))
    challenge: str = field(init=False)

    def __post_init__(self) -> None:
        self.challenge = base64.urlsafe_b64encode(
            hashlib.sha256(self.verifier.encode()).digest()
        ).rstrip(b"=").decode()


@dataclass
class CBAAuthorizationRequest:
    """Exact URL + body for the Entra CBA /authorize request."""

    cloud: CloudProfile
    client_id: str
    redirect_uri: str
    tenant: str = "common"
    pkce: PKCE = field(default_factory=PKCE)
    state: str = field(default_factory=lambda: secrets.token_urlsafe(24))

    def endpoint(self) -> str:
        base = self.cloud.authority
        return urlparse.urljoin(base, f"{self.tenant}/oauth2/v2.0/authorize")

    def authorization_url(self) -> str:
        return (
            self.endpoint()
            + "?"
            + urlparse.urlencode(
                {
                    "client_id": self.client_id,
                    "response_type": "code",
                    "redirect_uri": self.redirect_uri,
                    "scope": f"{self.cloud.resource_scope} openid profile offline_access",
                    "code_challenge": self.pkce.challenge,
                    "code_challenge_method": "S256",
                    "state": self.state,
                    "prompt": "login",
                }
            )
        )

    def token_request(self, code: str) -> dict[str, str]:
        """Body for the /oauth2/v2.0/token POST at the same cloud authority."""
        return {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": self.pkce.verifier,
            "scope": f"{self.cloud.resource_scope} openid profile offline_access",
        }


class CBAError(RuntimeError):
    """Raised when WebKitGTK rejects the smartcard during CBA."""

    def __init__(self, stage: str, detail: str = "") -> None:
        super().__init__(f"[CBA:{stage}] {detail}".strip())
        self.stage = stage


def piv_auth_selector() -> str:
    """PKCS#11 URI FreeRDP/WinPR treats as the PIV Authentication cert.

    This is the selector string passed to SCardTransmit/SCardGetProvidergroup
    when the Windows App client performs smartcard CBA: it matches the
    certificate with ID 01 and the PIV Authentication object ID. WebKitGTK
    similarly filters certificates by CKA_CERTIFICATE_TYPE + CKA_ID through
    the p11-kit-trust module on the host.
    """
    return "pkcs11:object=PIV%20AUTH%20cert"