import argparse
import datetime as dt
import http.server
import ipaddress
import os
import socket
import ssl
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KATALOG_CERT = os.path.join(REPO, "_certyfikat")
KATALOG = os.path.join(REPO, "_site")
CERT = os.path.join(KATALOG_CERT, "mapa.crt")
KLUCZ = os.path.join(KATALOG_CERT, "mapa.key")

# ADRESY IP:
def adresy_ip():
    ip = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip.add(info[4][0])
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ip)

# CERTYFIKAT SSL:
def utworz_certyfikat(ip):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    klucz = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nazwa = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mapa Qgis (lokalnie)")])
    san = [x509.DNSName("localhost"), x509.DNSName(socket.gethostname())]
    san += [x509.IPAddress(ipaddress.ip_address(a)) for a in ip]
    teraz = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(nazwa).issuer_name(nazwa)
            .public_key(klucz.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(teraz - dt.timedelta(days=1))
            .not_valid_after(teraz + dt.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(klucz, hashes.SHA256()))
    os.makedirs(KATALOG_CERT, exist_ok=True)
    with open(KLUCZ, "wb") as f:
        f.write(klucz.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                    serialization.NoEncryption()))
    with open(CERT, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print(f"Utworzono certyfikat dla: localhost, {', '.join(ip)}")

# OBSŁUGA ŻĄDAŃ HTTP:
class Obsluga(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=KATALOG, **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

# START SERWERA HTTPS:
def main():
    global KATALOG
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Serwer HTTPS mapy")
    p.add_argument("--port", type=int, default=8443)
    p.add_argument("--katalog", default=KATALOG, help="udostępniany folder (domyślnie _site)")
    a = p.parse_args()

    KATALOG = os.path.abspath(a.katalog)
    if not os.path.isfile(os.path.join(KATALOG, "index.html")):
        sys.exit(f"Brak {KATALOG}{os.sep}index.html – najpierw zbuduj stronę: python skrypty/strona.py")

    ip = adresy_ip()
    if not (os.path.exists(CERT) and os.path.exists(KLUCZ)):
        utworz_certyfikat(ip)

    kontekst = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    kontekst.load_cert_chain(CERT, KLUCZ)
    serwer = http.server.ThreadingHTTPServer(("0.0.0.0", a.port), Obsluga)
    serwer.socket = kontekst.wrap_socket(serwer.socket, server_side=True)

    print("Mapa działa przez HTTPS:")
    print(f"  https://localhost:{a.port}")
    for adres in ip:
        if adres != "127.0.0.1":
            print(f"  https://{adres}:{a.port}   (z innych urządzeń w tej samej sieci)")
    print("Zatrzymanie: Ctrl+C")
    try:
        serwer.serve_forever()
    except KeyboardInterrupt:
        print("\nZatrzymano.")


if __name__ == "__main__":
    main()
