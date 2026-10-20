"""LAN certificate generation (no network listener is started; nothing is added to any trust store)."""

from __future__ import annotations

import ipaddress

from cryptography import x509

from rescuebridge.certs import ensure_lan_certificate
from rescuebridge.config import load_settings


def test_lan_certificate_is_bound_to_the_ip_and_reused(tmp_path):
    settings = load_settings(data_dir=tmp_path)
    cert_path, key_path = ensure_lan_certificate(settings, "192.168.1.50")
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert ipaddress.ip_address("192.168.1.50") in san.get_values_for_type(x509.IPAddress)
    assert cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is False
    assert key_path.read_bytes().startswith(b"-----BEGIN PRIVATE KEY-----")
    again = ensure_lan_certificate(settings, "192.168.1.50")
    assert again == (cert_path, key_path)
    assert cert_path.read_bytes() == again[0].read_bytes()  # reused while valid, not regenerated
