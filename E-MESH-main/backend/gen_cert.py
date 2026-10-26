"""One-shot cert generator — run via: python gen_cert.py"""
import ipaddress, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

CERT_DIR  = Path(__file__).parent / "certs"
CERT_FILE = CERT_DIR / "cert.pem"
KEY_FILE  = CERT_DIR / "key.pem"
CERT_IPS  = ["192.168.137.1", "127.0.0.1"]
CERT_HOSTS = ["localhost"]
CERT_DAYS = 3650

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    print("ERROR: Run: pip install cryptography")
    sys.exit(1)

CERT_DIR.mkdir(exist_ok=True)
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([
    x509.NameAttribute(NameOID.COUNTRY_NAME, "IN"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "E-MESH Emergency Network"),
    x509.NameAttribute(NameOID.COMMON_NAME, "192.168.137.1"),
])
sans = [x509.DNSName(h) for h in CERT_HOSTS]
sans += [x509.IPAddress(ipaddress.IPv4Address(ip)) for ip in CERT_IPS]
now = datetime.now(timezone.utc)
cert = (
    x509.CertificateBuilder()
    .subject_name(name).issuer_name(name)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now)
    .not_valid_after(now + timedelta(days=CERT_DAYS))
    .add_extension(x509.SubjectAlternativeName(sans), critical=False)
    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    .sign(key, hashes.SHA256())
)
KEY_FILE.write_bytes(key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption(),
))
CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
print(f"[OK] cert.pem -> {CERT_FILE}")
print(f"[OK] key.pem  -> {KEY_FILE}")
print(f"[OK] Valid for: {', '.join(CERT_IPS + CERT_HOSTS)} for {CERT_DAYS} days")
