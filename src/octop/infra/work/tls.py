"""mTLS configuration for the fixed Work entry-to-runtime link."""

from __future__ import annotations

import os
import ssl
from pathlib import Path

_CA_ENV = "WORK_RUNTIME_MTLS_CA_FILE"
_CERT_ENV = "WORK_RUNTIME_MTLS_CERT_FILE"
_KEY_ENV = "WORK_RUNTIME_MTLS_KEY_FILE"


def runtime_mtls_paths() -> tuple[Path, Path, Path]:
    paths = (
        Path(os.environ.get(_CA_ENV, "").strip()),
        Path(os.environ.get(_CERT_ENV, "").strip()),
        Path(os.environ.get(_KEY_ENV, "").strip()),
    )
    if any(not str(path) or not path.is_file() for path in paths):
        raise RuntimeError("Work runtime mTLS requires readable CA, certificate, and key files")
    return paths


def runtime_client_ssl_context() -> ssl.SSLContext:
    ca_file, cert_file, key_file = runtime_mtls_paths()
    context = ssl.create_default_context(cafile=ca_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return context
