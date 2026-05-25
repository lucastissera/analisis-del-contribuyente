"""Lectura de certificados digitales ARCA/AFIP (.pfx/.p12 o .crt/.cer + .key)."""

from __future__ import annotations

import io
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cuit_en_arca.errores import CertificadoArchivoError

_EXT_CERT = frozenset({".crt", ".cer", ".pem"})
_EXT_KEY = frozenset({".key", ".pem"})
_EXT_PFX = frozenset({".pfx", ".p12"})

_ORIGENES_AFIP_TLS = (
    "https://auth.afip.gob.ar",
    "https://www.afip.gob.ar",
    "https://seti.afip.gob.ar",
    "https://serviciosweb.afip.gob.ar",
)


@dataclass(frozen=True)
class CredencialesCertificado:
    cuit_login: str
    cuit_representado: str
    """Config para Playwright context.client_certificates (misma estructura por origen)."""
    client_certificates: tuple[dict, ...]
    """Directorio temporal; debe borrarse tras la automatización."""
    temp_dir: str


def _solo_digitos_cuit(s: str, etiqueta: str) -> str:
    d = re.sub(r"\D", "", str(s))
    if len(d) != 11:
        raise CertificadoArchivoError(
            f"{etiqueta}: se esperaban 11 dígitos (valor recibido no normalizable)."
        )
    return d


def _extraer_cuit_de_pem(pem: bytes) -> str | None:
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        return None
    try:
        cert = x509.load_pem_x509_certificate(pem, default_backend())
    except Exception:
        try:
            from cryptography.hazmat.primitives.serialization import load_der_x509_certificate

            cert = load_der_x509_certificate(pem, default_backend())
        except Exception:
            return None
    for attr in cert.subject:
        val = str(attr.value)
        low = val.lower()
        if "cuit" in low or "cuil" in low or "cdi" in low:
            d = re.sub(r"\D", "", val)
            if len(d) >= 11:
                return d[-11:]
    for attr in cert.subject:
        val = str(attr.value)
        d = re.sub(r"\D", "", val)
        if len(d) == 11:
            return d
    return None


def _leer_pem_o_der(buf: bytes) -> bytes:
    if b"-----BEGIN" in buf:
        return buf
    try:
        from cryptography.hazmat.primitives.serialization import load_der_x509_certificate
        from cryptography.hazmat.primitives.serialization import Encoding
        from cryptography.hazmat.backends import default_backend

        cert = load_der_x509_certificate(buf, default_backend())
        return cert.public_bytes(Encoding.PEM)
    except Exception:
        return buf


def _normalizar_nombre(n: str) -> str:
    return Path(n).name.lower()


def construir_credenciales_certificado(
    *,
    archivo_pfx: io.BytesIO | None = None,
    nombre_pfx: str | None = None,
    archivo_cert: io.BytesIO | None = None,
    nombre_cert: str | None = None,
    archivo_key: io.BytesIO | None = None,
    nombre_key: str | None = None,
    passphrase: str | None = None,
    cuit_login_texto: str | None = None,
    cuit_representado_texto: str | None = None,
) -> CredencialesCertificado:
    """
    Arma credenciales y archivos temporales para Playwright (client_certificates).
    Requiere .pfx/.p12 **o** par certificado + clave privada.
    """
    tiene_pfx = archivo_pfx is not None and nombre_pfx
    tiene_par = archivo_cert is not None and archivo_key is not None and nombre_cert and nombre_key

    if not tiene_pfx and not tiene_par:
        raise CertificadoArchivoError(
            "Subí un archivo .pfx o .p12, o bien el certificado (.crt/.cer/.pem) "
            "junto con la clave privada (.key/.pem)."
        )

    if not (cuit_representado_texto or "").strip():
        raise CertificadoArchivoError(
            "Indicá el CUIT representado (contribuyente cuyos comprobantes querés descargar)."
        )
    cuit_repr = _solo_digitos_cuit(cuit_representado_texto.strip(), "CUIT representado")

    tmp = tempfile.mkdtemp(prefix="arca_cert_")
    client_entries: list[dict] = []
    cuit_desde_cert: str | None = None

    pwd = (passphrase or "").strip() or None

    if tiene_pfx:
        ext = Path(_normalizar_nombre(nombre_pfx)).suffix
        if ext not in _EXT_PFX:
            raise CertificadoArchivoError("El contenedor debe ser .pfx o .p12.")
        archivo_pfx.seek(0)
        raw_pfx = archivo_pfx.read()
        if not raw_pfx:
            raise CertificadoArchivoError("El archivo .pfx/.p12 está vacío.")
        pfx_path = Path(tmp) / f"client{ext}"
        pfx_path.write_bytes(raw_pfx)
        try:
            from cryptography.hazmat.primitives.serialization import pkcs12

            _, cert_obj, _ = pkcs12.load_key_and_certificates(
                raw_pfx, pwd.encode() if pwd else None
            )
            if cert_obj is not None:
                from cryptography.hazmat.primitives.serialization import Encoding

                pem = cert_obj.public_bytes(Encoding.PEM)
                cuit_desde_cert = _extraer_cuit_de_pem(pem)
        except ImportError:
            pass
        except Exception as exc:
            raise CertificadoArchivoError(
                "No se pudo leer el .pfx/.p12 (contraseña incorrecta o archivo dañado)."
            ) from exc
        for origin in _ORIGENES_AFIP_TLS:
            entry: dict = {"origin": origin, "pfxPath": str(pfx_path)}
            if pwd:
                entry["passphrase"] = pwd
            client_entries.append(entry)
    else:
        assert archivo_cert is not None and archivo_key is not None
        ext_c = Path(_normalizar_nombre(nombre_cert)).suffix
        ext_k = Path(_normalizar_nombre(nombre_key)).suffix
        if ext_c not in _EXT_CERT:
            raise CertificadoArchivoError(
                "Certificado: usá extensión .crt, .cer o .pem."
            )
        if ext_k not in _EXT_KEY:
            raise CertificadoArchivoError(
                "Clave privada: usá extensión .key o .pem."
            )
        archivo_cert.seek(0)
        archivo_key.seek(0)
        raw_c = archivo_cert.read()
        raw_k = archivo_key.read()
        if not raw_c or not raw_k:
            raise CertificadoArchivoError("El certificado o la clave privada está vacío.")
        pem_c = _leer_pem_o_der(raw_c)
        cuit_desde_cert = _extraer_cuit_de_pem(pem_c)
        cert_path = Path(tmp) / f"client{ext_c if ext_c != '.cer' else '.crt'}"
        key_path = Path(tmp) / f"client{ext_k}"
        cert_path.write_bytes(pem_c if pem_c.startswith(b"-----") else raw_c)
        key_path.write_bytes(raw_k)
        for origin in _ORIGENES_AFIP_TLS:
            entry = {
                "origin": origin,
                "certPath": str(cert_path),
                "keyPath": str(key_path),
            }
            if pwd:
                entry["passphrase"] = pwd
            client_entries.append(entry)

    cuit_log = (cuit_login_texto or "").strip()
    if cuit_log:
        cuit_login = _solo_digitos_cuit(cuit_log, "CUIT de login")
    elif cuit_desde_cert:
        cuit_login = cuit_desde_cert
    else:
        raise CertificadoArchivoError(
            "No se pudo obtener el CUIT del certificado. Completá el campo «CUIT de login»."
        )

    return CredencialesCertificado(
        cuit_login=cuit_login,
        cuit_representado=cuit_repr,
        client_certificates=tuple(client_entries),
        temp_dir=tmp,
    )


def limpiar_temporales_certificado(cred: CredencialesCertificado) -> None:
    import shutil

    try:
        shutil.rmtree(cred.temp_dir, ignore_errors=True)
    except Exception:
        pass
