#!/usr/bin/env python3
"""Genera logo-oscuro.gif animado desde logo-oscuro.png (loop seamless)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "static" / "logo-oscuro.png"
OUT_NAMES = ("logo-oscuro.gif",)

NUM_FRAMES = 48
FRAME_MS = 42
BOB_PX = 4.5
SWEEP_WIDTH = 140.0
SWEEP_STRENGTH = 0.38


def _masks(rgba: np.ndarray) -> dict[str, np.ndarray]:
    r, g, b, al = rgba[:, :, 0], rgba[:, :, 1], rgba[:, :, 2], rgba[:, :, 3]
    text = (r > 200) & (g > 200) & (b > 200) & (al > 128)
    cyan = (g > 150) & (b > 180) & (r < 120) & (al > 50) & ~text
    dark = (al > 30) & (r < 80) & (g < 100) & ~text & ~cyan
    swoosh = (al > 20) & ~text & ~cyan & ~dark & (b > 80)
    return {"text": text, "cyan": cyan, "dark": dark, "swoosh": swoosh}


def _layer(rgba: np.ndarray, mask: np.ndarray) -> np.ndarray:
    out = np.zeros_like(rgba)
    out[mask] = rgba[mask]
    return out


def _shift_vertical(layer: np.ndarray, dy: int) -> np.ndarray:
    if dy == 0:
        return layer.copy()
    h, w = layer.shape[:2]
    out = np.zeros_like(layer)
    if dy > 0:
        out[dy:, :, :] = layer[: h - dy, :, :]
    else:
        k = -dy
        out[: h - k, :, :] = layer[k:, :, :]
    return out


def _alpha_over(bottom: np.ndarray, top: np.ndarray) -> np.ndarray:
    """bottom, top: uint8 RGBA."""
    b = bottom.astype(np.float32)
    t = top.astype(np.float32)
    ta = t[:, :, 3:4] / 255.0
    ba = b[:, :, 3:4] / 255.0
    out_a = ta + ba * (1.0 - ta)
    out_rgb = np.zeros_like(b[:, :, :3])
    for c in range(3):
        out_rgb[:, :, c] = (t[:, :, c] * ta[:, :, 0] + b[:, :, c] * ba[:, :, 0] * (1.0 - ta[:, :, 0])) / np.maximum(
            out_a[:, :, 0], 1e-6
        )
    result = np.zeros_like(bottom)
    result[:, :, :3] = np.clip(out_rgb, 0, 255).astype(np.uint8)
    result[:, :, 3] = np.clip(out_a[:, :, 0] * 255, 0, 255).astype(np.uint8)
    return result


def _sweep_map(w: int, h: int, center_x: float) -> np.ndarray:
    xs = np.arange(w, dtype=np.float32)
    dist = np.abs(xs - center_x)
    stripe = np.exp(-(dist * dist) / (2.0 * (SWEEP_WIDTH * 0.35) ** 2))
    stripe = stripe * (1.0 - np.clip(dist / SWEEP_WIDTH, 0, 1) * 0.35)
    return np.broadcast_to(stripe, (h, w)).copy()


def _apply_sweep(canvas: np.ndarray, sweep: np.ndarray, mask: np.ndarray) -> None:
    """Brillo aditivo suave sobre borde y fondo (no texto)."""
    m = mask.astype(np.float32)
    glow = sweep * SWEEP_STRENGTH * m
    for c in range(3):
        if c == 0:
            add = glow * 55
        elif c == 1:
            add = glow * 120
        else:
            add = glow * 165
        ch = canvas[:, :, c].astype(np.float32)
        ch = np.minimum(255.0, ch + add)
        canvas[:, :, c] = ch.astype(np.uint8)
    alpha_boost = glow * 35
    canvas[:, :, 3] = np.minimum(
        255, canvas[:, :, 3].astype(np.float32) + alpha_boost
    ).astype(np.uint8)


def generar_gif(origen: Path, destino: Path) -> None:
    rgba = np.array(Image.open(origen).convert("RGBA"))
    h, w = rgba.shape[:2]
    mk = _masks(rgba)

    text_layer = _layer(rgba, mk["text"])
    border_layer = _layer(rgba, mk["cyan"])
    interior_layer = _layer(rgba, mk["dark"])
    swoosh_layer = _layer(rgba, mk["swoosh"])

    glow_targets = mk["cyan"] | mk["swoosh"] | mk["dark"]

    frames: list[Image.Image] = []
    for i in range(NUM_FRAMES):
        t = i / NUM_FRAMES
        dy = int(round(BOB_PX * math.sin(2.0 * math.pi * t)))
        sweep_x = t * (w + SWEEP_WIDTH * 2.0) - SWEEP_WIDTH

        canvas = np.zeros((h, w, 4), dtype=np.uint8)
        moved = _shift_vertical(swoosh_layer, dy)
        canvas = _alpha_over(canvas, moved)
        canvas = _alpha_over(canvas, interior_layer)
        canvas = _alpha_over(canvas, border_layer)

        sweep = _sweep_map(w, h, sweep_x)
        _apply_sweep(canvas, sweep, glow_targets)

        canvas = _alpha_over(canvas, text_layer)
        frames.append(Image.fromarray(canvas, mode="RGBA"))

    first, *rest = frames
    first_rgb = first.convert("RGB")
    palette_frames = [f.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT) for f in frames]
    palette_frames[0].save(
        destino,
        save_all=True,
        append_images=palette_frames[1:],
        duration=FRAME_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )


def _destinos() -> list[Path]:
    paths = [ROOT / "static" / name for name in OUT_NAMES]
    dist = ROOT / "dist" / "AnalisisIntegralContribuyente" / "_internal" / "static"
    if dist.is_dir():
        paths.append(dist / OUT_NAMES[0])
    return paths


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC
    if not src.is_file():
        print(f"No se encontró {src}", file=sys.stderr)
        return 1
    for out in _destinos():
        out.parent.mkdir(parents=True, exist_ok=True)
        generar_gif(src, out)
        print(f"Generado: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
