"""Convert the white-background lyrebird logo to transparent-background PNG.

Algorithm: dual-threshold alpha-from-luminance with color un-premultiply.

- min(R,G,B) <= INTERIOR_MAX     → alpha 255, color passes through
- INTERIOR_MAX < min <= EDGE_MAX → smooth alpha + un-premultiply white
- min > EDGE_MAX                 → alpha 0 (background, including near-white)

The un-premultiply step recovers the foreground color at anti-aliased edges so
the logo sits cleanly on both cream (#faf9f5) and dark navy (#181715) without
milky halos.

Run:
    python scripts/make_transparent_logo.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path("src/lyrebird/web/static/img/logo.png")
OUT_DIR = Path("src/lyrebird/web/static/img")

INTERIOR_MAX = 200  # min(R,G,B) <= this is treated as fully opaque interior
EDGE_MAX = 250      # min(R,G,B) > this is treated as background
BG_VALUE = 255      # the assumed background color (white)


def remove_white_background(img_rgb: Image.Image) -> Image.Image:
    rgb = np.array(img_rgb, dtype=np.float32)
    mn = rgb.min(axis=2)

    alpha = np.zeros_like(mn, dtype=np.float32)
    interior = mn <= INTERIOR_MAX
    alpha[interior] = 255.0
    edge = (mn > INTERIOR_MAX) & (mn <= EDGE_MAX)
    # Linear fade from EDGE_MAX→0 down to INTERIOR_MAX→255.
    alpha[edge] = (EDGE_MAX - mn[edge]) / (EDGE_MAX - INTERIOR_MAX) * 255.0
    # mn > EDGE_MAX stays alpha=0.

    out = rgb.copy()
    a_norm = (alpha[edge] / 255.0)[:, None]
    bg = np.full((edge.sum(), 3), BG_VALUE, dtype=np.float32)
    # orig = a*fg + (1-a)*bg  →  fg = (orig - (1-a)*bg) / a
    out[edge] = np.clip((rgb[edge] - (1.0 - a_norm) * bg) / np.maximum(a_norm, 1e-3), 0, 255)

    rgba = np.dstack([out, alpha]).astype(np.uint8)
    return Image.fromarray(rgba, mode="RGBA")


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"missing source: {SRC}")
    src = Image.open(SRC).convert("RGB")
    print(f"loaded {SRC} ({src.size[0]}x{src.size[1]})")
    full = remove_white_background(src)

    targets = [
        ("logo.png", src.size),
        ("logo-256.png", (256, 256)),
        ("logo-96.png", (96, 96)),
    ]
    for name, size in targets:
        path = OUT_DIR / name
        if size != full.size:
            # LANCZOS preserves edge quality at downsample.
            out = full.resize(size, Image.Resampling.LANCZOS)
        else:
            out = full
        out.save(path, optimize=True)
        arr = np.array(out)
        alpha = arr[..., 3]
        opaque = (alpha == 255).mean() * 100
        transparent = (alpha == 0).mean() * 100
        partial = 100 - opaque - transparent
        print(
            f"wrote {path} ({size[0]}x{size[1]}, RGBA): "
            f"opaque={opaque:.1f}%  partial={partial:.1f}%  transparent={transparent:.1f}%"
        )


if __name__ == "__main__":
    main()
