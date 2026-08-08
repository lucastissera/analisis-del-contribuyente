# Protección de propiedad intelectual del portable (P2.15)

## Veredicto práctico

La **licencia y el cupo viven en el servidor** (Neon + Render + device token + entitlements). Eso es la defensa comercial real.

Compilar todo el portable con **Nuitka/Cython** aportaría poco frente a un atacante motivado, y **rompe o encarece mucho** el empaquetado actual (Playwright + Chromium + PyInstaller). Por eso Nuitka completo queda **aplazado a propósito**.

| Enfoque | Estado |
|---------|--------|
| Servidor autoritativo (cupo, vigencia, login remoto) | Hecho (P1) |
| Entitlements firmados (offline limitado) | Hecho (P2.12) |
| Authenticode (editor conocido en Windows) | Pendiente de certificado de pago |
| PyInstaller con `optimize=2` (menos docstrings/asserts en bytecode) | Hecho en el `.spec` |
| Nuitka/Cython de núcleos | **Aplazado** (alto costo, ROI bajo con licencia server-side) |

## Qué implica `optimize=2`

En el build portable, Python se empaqueta en nivel de optimización 2:

- se omiten `assert`;
- se descartan docstrings en muchos módulos.

No es DRM. Solo eleva un poco el costo de lectura casual del bytecode.

## Si en el futuro se retoma Nuitka

Candidatos razonables (sin Playwright):

- lógica pura de Excel / cruce / reportes;
- **no** el driver de Chromium ni el entrypoint del `.exe` completo.

Pasos tentativos:

1. Probar un módulo aislado: `python -m nuitka --module ruta/modulo.py`
2. Validar tests y un build portable híbrido.
3. Solo entonces integrar al pipeline de `portable_build.py`.

## Regla de producto

No invertir en ofuscación pesada hasta que:

1. haya certificado Authenticode en distribución, y  
2. el modelo de negocio dependa de secretos que **no** puedan vivir solo en el servidor.
