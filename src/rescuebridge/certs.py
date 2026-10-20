"""Self-signed certificate for LAN HTTPS (phone microphone access needs a secure context).

The certificate is generated locally and stored in the RescueBridge data directory with a current-user-only
ACL. Nothing is added to any trust store: the phone shows a certificate warning that the person may choose to
accept for this one local address. See README "Phone over LAN".
"""

from __future__ import annotations

import datetime as dt
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from rescuebridge.config import Settings, host_name


def ensure_lan_certificate(settings: Settings, ip: str) -> tuple[Path, Path]:
    from rescuebridge.host.pipe import write_private_file

    cert_path = settings.cert_dir / f"lan-{ip}.crt"
    key_path = settings.cert_dir / f"lan-{ip}.key"
    if cert_path.exists() and key_path.exists():
        try:
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            if cert.not_valid_after_utc > dt.datetime.now(dt.UTC) + dt.timedelta(days=1):
                return cert_path, key_path
        except ValueError:
            pass
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"RescueBridge {host_name()}")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip)), x509.DNSName(host_name())]),
                       critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    settings.cert_dir.mkdir(parents=True, exist_ok=True)
    write_private_file(key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path
