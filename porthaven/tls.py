"""Trusted HTTPS for stable names: https://shop.localhost:7443/ with a lock in the browser.

Porthaven keeps a small certificate authority of its own in ~/.porthaven/tls (or uses mkcert's, when mkcert is
installed and its CA is there), and makes a certificate for each name the first time a browser asks for it.
Browsers reject a wildcard for *.localhost, so every name gets its own certificate. The CA is only trusted after
`porthaven https trust`, which asks your system (and you) for permission.

Certificates are made with the `openssl` command (on macOS, Linux and Git for Windows).
"""
from __future__ import annotations

import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

CA_NAME = "Porthaven Local CA"
NAME_OK = re.compile(r"^(?:[a-z0-9-]+\.)*localhost$")
LEAF_DAYS = 397


class TlsError(RuntimeError):
    pass


def openssl():
    found = shutil.which("openssl")
    if found:
        return found
    if os.name == "nt":
        for p in (r"C:\Program Files\Git\usr\bin\openssl.exe", r"C:\Program Files\Git\mingw64\bin\openssl.exe"):
            if os.path.exists(p):
                return p
    return None


def mkcert_ca():
    """mkcert's CA (already trusted when you ran `mkcert -install`), if mkcert is installed."""
    exe = shutil.which("mkcert")
    if not exe:
        return None
    try:
        root = subprocess.run([exe, "-CAROOT"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    cert, key = Path(root) / "rootCA.pem", Path(root) / "rootCA-key.pem"
    return (cert, key) if cert.is_file() and key.is_file() else None


def _run(args, cwd=None):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=30, cwd=cwd)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise TlsError(f"openssl failed to run: {err}") from err
    if out.returncode:
        raise TlsError(f"openssl failed: {(out.stderr or out.stdout).strip()[:400]}")
    return out.stdout


class Authority:
    def __init__(self, root, use_mkcert=True):
        self.use_mkcert = use_mkcert
        self.dir = Path(root) / "tls"
        self.hosts = self.dir / "hosts"
        self.lock = threading.Lock()
        self.contexts = {}

    # ---------------------------------------------------------------- the CA
    @property
    def ca(self):
        """(cert, key, source): mkcert's CA when present, else Porthaven's own."""
        mk = mkcert_ca() if self.use_mkcert else None
        if mk:
            return mk[0], mk[1], "mkcert"
        return self.dir / "ca.pem", self.dir / "ca-key.pem", "porthaven"

    def ready(self):
        cert, key, _ = self.ca
        return cert.is_file() and key.is_file()

    def ensure_ca(self):
        cert, key, source = self.ca
        if cert.is_file() and key.is_file():
            return cert
        exe = openssl()
        if not exe:
            raise TlsError("HTTPS needs the `openssl` command (macOS and Linux have it; on Windows install Git for Windows) "
                           "or mkcert.")
        self.dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            cnf = Path(tmp) / "ca.cnf"
            cnf.write_text(f"""[req]
distinguished_name = dn
prompt = no
x509_extensions = v3
[dn]
CN = {CA_NAME}
O = Porthaven
OU = {os.environ.get("USER") or os.environ.get("USERNAME") or "local"}
[v3]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
""")
            _run([exe, "req", "-x509", "-new", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "3650",
                  "-keyout", str(key), "-out", str(cert), "-config", str(cnf)])
        try:
            os.chmod(key, 0o600)
        except OSError:
            pass
        return cert

    # ---------------------------------------------------------------- one certificate per name
    def leaf(self, name):
        """(cert path, key path) for a *.localhost name, made (or remade) when needed."""
        name = name.lower().rstrip(".")
        if not NAME_OK.match(name) or len(name) > 200:
            raise TlsError(f"{name} is not a .localhost name.")
        ca_cert, ca_key, _ = self.ca
        self.ensure_ca()
        cert, key = self.hosts / f"{name}.pem", self.hosts / f"{name}-key.pem"
        fresh = cert.is_file() and key.is_file() and cert.stat().st_mtime > ca_cert.stat().st_mtime \
            and time.time() - cert.stat().st_mtime < (LEAF_DAYS - 30) * 86400
        if fresh:
            return cert, key
        exe = openssl()
        if not exe:
            raise TlsError("HTTPS needs the `openssl` command.")
        self.hosts.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            csr, ext = Path(tmp) / "req.csr", Path(tmp) / "ext.cnf"
            ext.write_text(f"""basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = DNS:{name}
""")
            _run([exe, "req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(csr), "-subj", f"/CN={name}"])
            _run([exe, "x509", "-req", "-in", str(csr), "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial",
                  "-CAserial", str(Path(tmp) / "ca.srl"), "-days", str(LEAF_DAYS), "-sha256", "-extfile", str(ext), "-out", str(cert)])
        try:
            os.chmod(key, 0o600)
        except OSError:
            pass
        return cert, key

    def context_for(self, name):
        with self.lock:
            ctx = self.contexts.get(name)
            if ctx:
                return ctx
            cert, key = self.leaf(name)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(str(cert), str(key))
            self.contexts[name] = ctx
            return ctx

    def server_context(self):
        """The context the HTTPS listener starts with; it swaps in each name's certificate during the handshake."""
        base = self.context_for("localhost")

        def pick(sock, server_name, _ctx):
            if server_name and server_name != "localhost":
                try:
                    sock.context = self.context_for(server_name.lower())
                except (TlsError, ssl.SSLError, OSError):
                    return ssl.ALERT_DESCRIPTION_UNRECOGNIZED_NAME
            return None
        base.sni_callback = pick
        return base

    def reset(self):
        """Forget the certificates made so far (after the CA changed)."""
        with self.lock:
            self.contexts.clear()
        shutil.rmtree(self.hosts, ignore_errors=True)

    # ---------------------------------------------------------------- trust
    def trusted(self):
        """True / False when Porthaven can tell whether this system trusts the CA, None when it cannot."""
        cert, _, _ = self.ca
        if not cert.is_file():
            return False
        try:
            if sys.platform == "darwin":
                out = subprocess.run(["security", "verify-cert", "-c", str(cert)], capture_output=True, timeout=10)
                return out.returncode == 0
            if os.name == "nt":
                out = subprocess.run(["certutil", "-user", "-verifystore", "Root", CA_NAME], capture_output=True, timeout=10)
                return out.returncode == 0
            pem = cert.read_text().strip()
            for bundle in ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/cert.pem"):
                try:
                    if pem in Path(bundle).read_text():
                        return True
                except OSError:
                    continue
            return False
        except (OSError, subprocess.TimeoutExpired):
            return None

    def trust_commands(self):
        """The commands that make this system trust the CA (each asks for your permission)."""
        cert, _, source = self.ca
        if source == "mkcert":
            return [["mkcert", "-install"]]
        if sys.platform == "darwin":
            keychain = str(Path.home() / "Library" / "Keychains" / "login.keychain-db")
            return [["security", "add-trusted-cert", "-r", "trustRoot", "-k", keychain, str(cert)]]
        if os.name == "nt":
            return [["certutil", "-user", "-addstore", "Root", str(cert)]]
        cmds = [["sudo", "cp", str(cert), "/usr/local/share/ca-certificates/porthaven-local-ca.crt"], ["sudo", "update-ca-certificates"]]
        if shutil.which("certutil"):   # Chrome and Firefox on Linux keep their own list
            nssdb = f"sql:{Path.home() / '.pki' / 'nssdb'}"
            cmds.append(["certutil", "-d", nssdb, "-A", "-t", "C,,", "-n", CA_NAME, "-i", str(cert)])
        return cmds

    def status(self):
        cert, _, source = self.ca
        return {"ca": str(cert), "source": source, "exists": cert.is_file(), "openssl": bool(openssl()), "mkcert": bool(shutil.which("mkcert")),
                "trusted": self.trusted() if cert.is_file() else False,
                "trustCommands": [" ".join(f'"{a}"' if " " in a else a for a in c) for c in self.trust_commands()]}
