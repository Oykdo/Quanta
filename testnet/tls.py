"""Mutual TLS 1.3 for an explicit private-LAN listener; wallet keys bind client identity."""
from datetime import datetime, timedelta, timezone
import ipaddress
from pathlib import Path
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from exchange.crypto import account_id, public_hex
from v2.storage import OutputBudget


def _write(path, payload, budget):
    path = Path(path)
    budget._check(len(payload))
    with path.open('xb') as file:
        file.write(payload)


def _private(key, password):
    if len(password) < 12:
        raise ValueError('A local private-key passphrase of at least 12 characters is required')
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.BestAvailableEncryption(password.encode('utf-8')))


def make_ca(folder, password, server_hosts):
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    budget = OutputBudget(folder, 1_000_000)
    now = datetime.now(timezone.utc)
    ca_key, server_key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Quanta LAN pilot CA')])
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
          .not_valid_after(now+timedelta(days=365)).add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), True)
          .sign(ca_key, hashes.SHA256()))
    sans = []
    for host in server_hosts:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            sans.append(x509.DNSName(host))
    if not sans:
        raise ValueError('At least one explicit server name or IP is required')
    server = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Quanta LAN server')]))
              .issuer_name(ca.subject).public_key(server_key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=30))
              .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
              .add_extension(x509.SubjectAlternativeName(sans), False)
              .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), True)
              .sign(ca_key, hashes.SHA256()))
    for name, payload in (('ca.key.pem', _private(ca_key, password)), ('server.key.pem', _private(server_key, password)),
                          ('ca.crt', ca.public_bytes(serialization.Encoding.PEM)),
                          ('server.crt', server.public_bytes(serialization.Encoding.PEM))):
        _write(folder/name, payload, budget)


def make_csr(key):
    who = account_id(public_hex(key))
    return (x509.CertificateSigningRequestBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, who)]))
            .sign(key, None).public_bytes(serialization.Encoding.PEM))


def issue_client(pki, csr_bytes, password, allowed):
    pki = Path(pki)
    csr = x509.load_pem_x509_csr(csr_bytes)
    if not csr.is_signature_valid or not isinstance(csr.public_key(), ed25519.Ed25519PublicKey):
        raise ValueError('A valid wallet Ed25519 CSR is required')
    public = csr.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    who = account_id(public)
    if who not in allowed:
        raise ValueError('CSR wallet is not admitted in this ledger plan')
    ca = x509.load_pem_x509_certificate((pki/'ca.crt').read_bytes())
    ca_key = serialization.load_pem_private_key((pki/'ca.key.pem').read_bytes(), password.encode('utf-8'))
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, who)]))
            .issuer_name(ca.subject).public_key(csr.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), True)
            .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier('urn:quanta:wallet:'+who)]), False)
            .sign(ca_key, hashes.SHA256()))
    return who, cert.public_bytes(serialization.Encoding.PEM)


def server_context(ca, certificate, key, password):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cafile=str(ca))
    context.load_cert_chain(str(certificate), str(key), password)
    return context


def client_context(ca, certificate, key, password):
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca))
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(str(certificate), str(key), password)
    return context


def peer_wallet(connection):
    cert = x509.load_der_x509_certificate(connection.getpeercert(binary_form=True))
    public = cert.public_key()
    if not isinstance(public, ed25519.Ed25519PublicKey):
        raise ValueError('Client certificate must use the wallet Ed25519 key')
    return account_id(public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex())
