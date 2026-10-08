"""Real TLS handshakes: no HTTP mocks and no verification bypass."""

import datetime as dt
import ipaddress
import socket
import ssl
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def certificates(tmp_path, *, expired=False, san="127.0.0.1"):
    now = dt.datetime.now(dt.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Ephemeral TLS test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=2))
        .not_valid_after(now + dt.timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, None, None), critical=True
        )
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Ephemeral test server")]))
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=2))
        .not_valid_after(now - dt.timedelta(days=1) if expired else now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(san))]), critical=False
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    for filename, contents in [
        ("ca.pem", ca.public_bytes(serialization.Encoding.PEM)),
        ("leaf.pem", leaf.public_bytes(serialization.Encoding.PEM)),
        (
            "key.pem",
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        ),
    ]:
        path = tmp_path / filename
        path.write_bytes(contents)
        path.chmod(0o600)
    return tmp_path / "ca.pem", tmp_path / "leaf.pem", tmp_path / "key.pem"


def handshake(cert, key, context, hostname="127.0.0.1"):
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.minimum_version = ssl.TLSVersion.TLSv1_2
    server_context.load_cert_chain(cert, key)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)

        def serve_once():
            try:
                with listener.accept()[0] as raw:
                    raw.settimeout(5)
                    with server_context.wrap_socket(raw, server_side=True) as connection:
                        connection.sendall(b"verified")
            except (ssl.SSLError, OSError):
                # Negative tests intentionally cause a fatal TLS alert on the server.
                pass

        thread = threading.Thread(target=serve_once, daemon=True)
        thread.start()
        try:
            with socket.create_connection(listener.getsockname(), timeout=5) as raw:
                with context.wrap_socket(raw, server_hostname=hostname) as connection:
                    return connection.recv(8)
        finally:
            thread.join(timeout=6)
            assert not thread.is_alive()


def test_trusted_ca_and_correct_ip_succeed(tmp_path):
    ca, cert, key = certificates(tmp_path)
    assert handshake(cert, key, ssl.create_default_context(cafile=str(ca))) == b"verified"


@pytest.mark.parametrize("case", ["unknown_ca", "wrong_ca", "ip_mismatch", "expired"])
def test_untrusted_or_invalid_certificate_is_rejected(tmp_path, case):
    ca, cert, key = certificates(tmp_path, expired=case == "expired")
    context = ssl.create_default_context()
    if case == "wrong_ca":
        other = tmp_path / "other"
        other.mkdir()
        ca, _, _ = certificates(other)
    if case != "unknown_ca":
        context.load_verify_locations(cafile=str(ca))
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED
    with pytest.raises(ssl.SSLCertVerificationError):
        handshake(cert, key, context, "127.0.0.2" if case == "ip_mismatch" else "127.0.0.1")


def test_mismatched_private_key_refused_before_listening(tmp_path):
    _, cert, _ = certificates(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    _, _, wrong_key = certificates(other)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with pytest.raises(ssl.SSLError):
        context.load_cert_chain(cert, wrong_key)
