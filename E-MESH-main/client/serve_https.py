import os
import ssl
import socket
import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

def generate_self_signed_cert(cert_file, key_file):
    if os.path.exists(cert_file) and os.path.exists(key_file):
        print("Using existing certificate files.")
        return
        
    print("Generating self-signed certificate...")
    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Generate certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
    ])
    
    now = datetime.datetime.now(datetime.timezone.utc)
    
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        now
    ).not_valid_after(
        # Valid for 365 days
        now + datetime.timedelta(days=365)
    ).add_extension(
        x509.SubjectAlternativeName([x509.DNSName(u"localhost")]),
        critical=False,
    ).sign(private_key, hashes.SHA256())

    # Write private key
    with open(key_file, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    # Write certificate
    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

if __name__ == "__main__":
    PORT = 3443 # Using 3443 to avoid conflict with existing 3000
    CERT_FILE = 'cert.pem'
    KEY_FILE = 'key.pem'
    
    generate_self_signed_cert(CERT_FILE, KEY_FILE)
    
    httpd = HTTPServer(('0.0.0.0', PORT), SimpleHTTPRequestHandler)
    
    # Wrap with SSL
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    
    local_ip = get_local_ip()
    print("\n" + "="*50)
    print(f"🔒 SECURE HTTPS SERVER RUNNING ON PORT {PORT}")
    print("="*50)
    print(f"\nAccess it securely on your phone at:")
    print(f"👉 https://{local_ip}:{PORT}")
    print("\nNote: Your browser will say 'Connection is not private'.")
    print("Click 'Advanced' -> 'Proceed to [IP] (unsafe)'.")
    print("Once loaded, the GPS Geolocation API will work!")
    print("\nPress Ctrl+C to stop.")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
