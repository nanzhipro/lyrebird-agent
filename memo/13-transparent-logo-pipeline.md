# Memo 13 — Transparent logo pipeline

Source artwork shipped as 8-bit RGB on a near-white (but not pure) background. The logo lives in three places (nav 28 px on cream, hero 88 px on cream, footer 24 px on dark navy with `opacity: 0.9`). On dark navy the white background read as a white rectangle, fighting the canvas-tinted text the footer was already balancing — see memo/09's "treat the logo as an illustration, not a brand color" rule.

## Why chroma key is wrong here

The obvious one-liner is `magick logo.png -transparent white logo.png`. It catches pure `#ffffff` pixels and leaves everything else alone. On this asset that misses ~85% of the background (the corners read `(253-254, 252-254, 253-254)` — JPEG-y near-white from the export) and leaves a milky halo at every anti-aliased edge on dark surfaces. You can widen the fuzz, but that either eats interior pixels or still leaves halo.

The right algorithm is **alpha-from-luminance with color un-premultiply**: assume foreground was originally composited over white, recover the alpha from how non-white each pixel is, then back out the un-premultiplied foreground color so edge pixels don't carry baked-in white.

## The actual algorithm

For each pixel `(R, G, B)`:

- `m = min(R, G, B)` — the "non-whiteness" measure (saturated colors have at least one low channel; white has all channels = 255).
- Dual-threshold mapping:
  - `m ≤ 200`  → α = 255  (logo interior, fully opaque, color passes through)
  - `200 < m ≤ 250` → α fades linearly to 0 + **un-premultiply white**: `fg = (orig − (1 − a)·255) / a`
  - `m > 250` → α = 0  (background, including 253-254 near-white)

The dual threshold is chosen from the histogram of the actual artwork (`scripts/make_transparent_logo.py` prints it on every run, repeat it after re-exports):

| `min(R,G,B)` band | share of pixels | meaning |
|---|---|---|
| ≤ 200 | ~12% | logo interior — saturated blue/purple, median min=41, p75=65 |
| 200–250 | ~2% | anti-aliased edge band |
| > 250 | ~86% | white background (including the off-white tail) |

The 200/250 thresholds give a 50-level AA band, wide enough for clean edge fading at 88 px / 256 px downsamples and narrow enough that no interior pixel ever falls into it. The un-premultiply is what makes the footer-on-dark composite look right — without it, the edge band would still carry residual white and read as a halo.

## Don't use this algorithm if

- The logo has **pastel** interior colors (e.g. light grey, light yellow). Their `min(R,G,B)` would be > 200 and they would be treated as edge/background. For the current blue-purple gradient artwork the lightest interior `min` is ~41 so we have huge margin; a future logo could break this.
- The background isn't approximately white. The un-premultiply assumes `BG_VALUE = 255`. A different background would need a different recovery formula and the histogram would need to be re-inspected.

If either condition changes, switch to **flood-fill from corners with a tolerance**: pixels reachable from the corners through near-white are background candidates; interior pastel pixels are protected because they're not reachable. More code, but robust to any palette.

## Operational notes

- `scripts/make_transparent_logo.py` reads `src/lyrebird/web/static/img/logo.png` and writes all three sizes (`.png` 2048, `-256.png`, `-96.png`) as RGBA. LANCZOS downsample for the smaller sizes — keeps the edge AA crisp at 96 px (the size that goes in the footer).
- Run it whenever the source logo is replaced. The script prints the opaque/partial/transparent split per output so you can sanity-check (current run: 12.3% / 1.5% / 86.2% at full size).
- After regenerating, **bump `?v=N`** on the four `<img src=".../logo-...png">` references in `src/lyrebird/web/static/index.html`. FastAPI's `StaticFiles` sends long-cache headers; browsers don't refetch on simple reload. Same reason CSS/JS get bumped (CLAUDE.md → "Static-asset versioning"). I bumped to `?v=2` for this change.

## Verification

The three-surface composite (cream + dark navy + coral + magenta checker) is the cheapest "does it have a halo" test — magenta-on-blue exposes any leftover white in the edge band instantly. The verification script lives inline in the session transcript; you can rebuild it from the same Pillow + alpha_composite primitives in five lines. Final live check is `/browse` of nav / hero / footer screenshots against the running uvicorn — what shipped passed those.
