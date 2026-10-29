#!/usr/bin/env python3
"""Build the schematic hero dot field from the Z3 portrait.

The source portrait belongs to the site owner. It is not stored in this
repository and is not copied into the output. Pass a local path:

    python3 tools/build-hero-dots.py --source /path/to/vorlage.png

Requires Pillow and numpy. Writes assets/hero-dots-data.js, a same-origin
script of packed points (no network fetch at runtime).
"""

from __future__ import annotations

import argparse
import base64
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "assets" / "hero-dots-data.js"

# Image aspect of the portrait. The runtime uses the same ratio.
ASPECT_W = 1402
ASPECT_H = 1122

PROC_W = 1100

# 4-bit palette indices. 0 is unused (empty).
# Radii and colours live in the renderer so the file stays small.
JACKET = 1
HAIR = 2
FACE = 3
FACE_LIT = 4
SKIN = 5
LAMP = 6
LAMP_RED = 7
LAMP_AMBER = 8
BLUEPRINT = 9
BLUEPRINT_DIM = 10
CONTOUR = 11
CHASSIS = 12
GLASSES = 13

BAYER_8 = np.array(
    [
        [0, 32, 8, 40, 2, 34, 10, 42],
        [48, 16, 56, 24, 50, 18, 58, 26],
        [12, 44, 4, 36, 14, 46, 6, 38],
        [60, 28, 52, 20, 62, 30, 54, 22],
        [3, 35, 11, 43, 1, 33, 9, 41],
        [51, 19, 59, 27, 49, 17, 57, 25],
        [15, 47, 7, 39, 13, 45, 5, 37],
        [63, 31, 55, 23, 61, 29, 53, 21],
    ],
    dtype=np.float32,
) / 64.0


def blur(arr: np.ndarray, radius: float) -> np.ndarray:
    # Pillow's Gaussian blur is implemented for 8-bit modes. Values here are
    # luminances and masks, so 8-bit is enough for a halftone.
    im = Image.fromarray(np.clip(np.rint(arr), 0, 255).astype(np.uint8), mode="L")
    return np.asarray(im.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32)


def morph(mask: np.ndarray, size: int, kind: str) -> np.ndarray:
    im = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    filt = ImageFilter.MaxFilter(size) if kind == "max" else ImageFilter.MinFilter(size)
    return np.asarray(im.filter(filt), dtype=np.uint8) > 128


def masked_blur(values: np.ndarray, weight: np.ndarray, radius: float) -> np.ndarray:
    w = blur(weight.astype(np.float32) * 255.0, radius) / 255.0
    num = blur(values.astype(np.float32) * weight.astype(np.float32), radius)
    return num / np.maximum(w, 1e-3)


def pack_points(points: list[tuple[int, int, int]]) -> bytes:
    out = bytearray()
    for x, y, color in points:
        x = 0 if x < 0 else 1023 if x > 1023 else x
        y = 0 if y < 0 else 1023 if y > 1023 else y
        color &= 15
        out.append(x >> 2)
        out.append(((x & 3) << 6) | (y >> 4))
        out.append(((y & 15) << 4) | color)
    return bytes(out)


def quantize(px: float, py: float, w: int, h: int, color: int) -> tuple[int, int, int]:
    x = int(round(px / (w - 1) * 1023))
    y = int(round(py / (h - 1) * 1023))
    return x, y, color


def prepare(source: Path):
    im = Image.open(source).convert("RGB")
    proc_h = int(round(PROC_W * im.height / im.width))
    im = im.resize((PROC_W, proc_h), Image.Resampling.LANCZOS)
    arr = np.asarray(im).astype(np.float32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    h, w = lum.shape

    blue = (b > r + 28) & (b > 90) & (g > r + 12) & (b > g - 10)
    # Pull the subject mask a few pixels over the blue fringe.
    blue = morph(blue, 5, "min")
    subject = ~blue

    # Console is the dark machine on the right. The suit stays with the person,
    # even where it sits low in the frame.
    xs = np.arange(w, dtype=np.float32)[None, :]
    ys = np.arange(h, dtype=np.float32)[:, None]
    panel = subject & (lum < 74) & (xs > w * 0.57) & (ys > h * 0.32) & (ys < h * 0.73)
    desk = subject & (lum < 62) & (ys >= h * 0.68) & (xs > w * 0.50)
    console = panel | desk
    person = subject & ~console

    weight = person.astype(np.float32)
    tone_soft = masked_blur(lum, weight, 4.4)
    tone_detail = masked_blur(lum, weight, 1.1)
    tone = np.where(tone_detail + 22 < tone_soft, tone_detail, tone_soft)

    return {
        "lum": lum,
        "r": r,
        "g": g,
        "b": b,
        "h": h,
        "w": w,
        "blue": blue,
        "subject": subject,
        "person": person,
        "console": console,
        "tone": tone,
        "xs": xs,
        "ys": ys,
    }


def strict_peaks(score: np.ndarray, radius: int) -> np.ndarray:
    """True where score is strictly greater than every pixel in a square neighbourhood."""
    peak = np.ones(score.shape, dtype=bool)
    # Step by 2 inside the radius; buttons are wide enough that this still
    # separates one lamp from the next and ignores flat plateaus.
    for dy in range(-radius, radius + 1, 2):
        for dx in range(-radius, radius + 1, 2):
            if dx == 0 and dy == 0:
                continue
            shifted = np.roll(np.roll(score, dy, axis=0), dx, axis=1)
            peak &= score > shifted
    return peak


def button_points(ctx) -> list[tuple[int, int, int]]:
    lum, r, g, b = ctx["lum"], ctx["r"], ctx["g"], ctx["b"]
    h, w = ctx["h"], ctx["w"]
    local = blur(lum, 6)
    red = (r > 185) & (g < 90) & (b < 75) & (r > g + 90)
    amber = (r > 200) & (g > 145) & (b < 90) & (g > b + 70)
    white = (lum > 176) & (np.abs(r - g) < 36) & (np.abs(g - b) < 42) & (lum > local + 55)
    score = np.zeros_like(lum)
    score[white] = lum[white]
    score[amber] = np.maximum(score[amber], 230)
    score[red] = 255
    # Lamps sit on the dark machine. Reflections of a whole row are wide and
    # bright; a real key is a small island, so reject high local density.
    bright = ((lum > 155) | red | amber).astype(np.float32)
    density = blur(bright * 255.0, 5) / 255.0
    on_machine = (ctx["xs"] > w * 0.42) & (ctx["ys"] > h * 0.36) & (local < 120) & (density < 0.42)
    score[~on_machine] = 0
    score[ctx["blue"]] = 0

    # A lamp is a small bright island: dark in most directions around it.
    # Specular streaks on the desk fail that test.
    ring = np.zeros_like(lum)
    for ang in range(8):
        theta = ang * np.pi / 4
        dy = int(round(np.sin(theta) * 13))
        dx = int(round(np.cos(theta) * 13))
        shifted = np.roll(np.roll(lum, dy, axis=0), dx, axis=1)
        ring += (shifted < 100).astype(np.float32)
    ring /= 8.0
    score[ring < 0.75] = 0
    pick = strict_peaks(score, 11) & (score > 160)
    pts = []
    ys, xs = np.where(pick)
    for y, x in zip(ys.tolist(), xs.tolist()):
        if red[y, x]:
            color = LAMP_RED
        elif amber[y, x]:
            color = LAMP_AMBER
        else:
            color = LAMP
        pts.append(quantize(x, y, w, h, color))
    return pts


def outline_mask(mask: np.ndarray, band: int) -> np.ndarray:
    size = band if band % 2 == 1 else band + 1
    dilated = morph(mask, size, "max")
    eroded = morph(mask, max(3, size - 2), "min")
    return dilated & ~eroded


def sample_profile(ctx, step: int, blueprint_step: int, buttons: list[tuple[int, int, int]]):
    h, w = ctx["h"], ctx["w"]
    tone = ctx["tone"]
    person = ctx["person"]
    console = ctx["console"]
    blue = ctx["blue"]
    lum = ctx["lum"]

    # Smooth the silhouette so hair engraving does not become a solid ribbon.
    person_solid = morph(morph(person, 11, "max"), 9, "min")
    console_solid = morph(morph(console, 7, "max"), 7, "min")
    person_edge = outline_mask(person_solid, 5)
    chassis_edge = outline_mask(console_solid, 5)
    glasses = person & (tone < 58) & (ctx["ys"] < h * 0.56) & (ctx["xs"] < w * 0.70) & (ctx["xs"] > w * 0.12)

    pts: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int]] = set()

    def add(x: float, y: float, color: int):
        q = quantize(x, y, w, h, color)
        key = (q[0], q[1])
        if key in seen:
            return
        seen.add(key)
        pts.append(q)

    for y in range(step // 2, h, step):
        by = int(y / step) % 8
        row_bayer = BAYER_8[by]
        for x in range(step // 2, w, step):
            bx = int(x / step) % 8
            threshold = float(row_bayer[bx])
            if person_edge[y, x] and threshold > 0.42:
                add(x, y, CONTOUR)
                continue
            if glasses[y, x]:
                # Thick frames read as gaps in the face field.
                continue
            if person[y, x]:
                norm = float(tone[y, x]) / 255.0
                # Posterized halftone. The dark suit is only a sparse stipple.
                if norm > 0.40 and norm * 0.9 > threshold * 0.72:
                    if norm > 0.74:
                        color = SKIN
                    elif norm > 0.60:
                        color = FACE_LIT
                    elif norm > 0.48:
                        color = FACE
                    else:
                        color = HAIR
                    add(x, y, color)
                elif norm > 0.09 and threshold > 0.80:
                    add(x, y, JACKET)
                continue
            if chassis_edge[y, x] and threshold > 0.40:
                add(x, y, CHASSIS)

    # Blueprint lines: local contrast inside the blue field, sparsely.
    local = blur(lum, 2.2)
    dev = np.abs(lum - local)
    bstep = blueprint_step
    for y in range(bstep // 2, h, bstep):
        for x in range(bstep // 2, w, bstep):
            if not blue[y, x]:
                continue
            d = float(dev[y, x])
            if d < 11:
                continue
            # Drop the flattest paper so the field stays airy.
            if d < 18 and ((x // bstep + y // bstep) % 3):
                continue
            add(x, y, BLUEPRINT if d > 26 else BLUEPRINT_DIM)

    for q in buttons:
        key = (q[0], q[1])
        if key in seen:
            # Lamps win over chassis dots that landed on the same cell.
            pts[:] = [p for p in pts if (p[0], p[1]) != key]
            seen.discard(key)
        seen.add(key)
        pts.append(q)

    return pts


def render_preview(points: list[tuple[int, int, int]], canvas, mobile: bool, path: Path, veil: bool = True):
    cw, ch = canvas
    aspect = ASPECT_W / ASPECT_H
    if mobile:
        dw = cw * 1.04
        dh = dw / aspect
        if dh > ch * 0.78:
            dh = ch * 0.78
            dw = dh * aspect
        ox = (cw - dw) / 2
        oy = ch * 0.02
    else:
        dh = ch * 1.02
        dw = dh * aspect
        if dw < cw * 0.92:
            dw = cw * 0.96
            dh = dw / aspect
        ox = (cw - dw) / 2
        oy = -ch * 0.015

    pal = {
        JACKET: (118, 114, 108, 150),
        HAIR: (158, 154, 146, 180),
        FACE: (186, 180, 170, 200),
        FACE_LIT: (214, 208, 196, 220),
        SKIN: (228, 222, 210, 230),
        LAMP: (236, 236, 232, 235),
        LAMP_RED: (196, 54, 48, 230),
        LAMP_AMBER: (196, 154, 64, 230),
        BLUEPRINT: (78, 112, 136, 130),
        BLUEPRINT_DIM: (42, 64, 80, 80),
        CONTOUR: (168, 166, 160, 190),
        CHASSIS: (92, 96, 102, 120),
        GLASSES: (210, 214, 218, 210),
    }
    scale = {
        JACKET: 0.85,
        HAIR: 1.0,
        FACE: 1.15,
        FACE_LIT: 1.25,
        SKIN: 1.3,
        LAMP: 1.55,
        LAMP_RED: 1.45,
        LAMP_AMBER: 1.45,
        BLUEPRINT: 0.75,
        BLUEPRINT_DIM: 0.65,
        CONTOUR: 1.05,
        CHASSIS: 0.8,
        GLASSES: 1.05,
    }
    base = 1.05 if mobile else 1.45
    img = Image.new("RGBA", (cw, ch), (10, 10, 10, 255))
    layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for x, y, color in points:
        cx = ox + (x / 1023) * dw
        cy = oy + (y / 1023) * dh
        rad = base * scale[color]
        fill = pal[color]
        draw.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=fill)
    img = Image.alpha_composite(img, layer)

    if veil:
        # Approximate the text veil so the preview matches the page.
        veil_arr = np.zeros((ch, cw, 4), dtype=np.uint8)
        ys = np.linspace(0, 1, ch)
        alpha = np.clip((ys - 0.34) / 0.46, 0, 1) ** 1.15
        alpha = (alpha * 235).astype(np.uint8)
        veil_arr[:, :, 3] = alpha[:, None]
        veil_arr[:, :, 0] = 10
        veil_arr[:, :, 1] = 10
        veil_arr[:, :, 2] = 10
        img = Image.alpha_composite(img, Image.fromarray(veil_arr, mode="RGBA"))
    img.convert("RGB").save(path, quality=90)
    print(f"preview {path} points={len(points)} canvas={cw}x{ch}")


def write_js(path: Path, mobile: bytes, desktop: bytes):
    payload = (
        "/* Generated by tools/build-hero-dots.py. Packed points, not the source image. */\n"
        "self.ZUSE_DOTS={m:"
        + '"'
        + base64.b64encode(mobile).decode("ascii")
        + '",d:"'
        + base64.b64encode(desktop).decode("ascii")
        + '"};\n'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="ascii")
    print(f"wrote {path} ({len(payload)} bytes, mobile {len(mobile)} raw, desktop {len(desktop)} raw)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="local portrait PNG, not committed")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--preview-dir", type=Path, default=None, help="write fit previews, not committed")
    args = parser.parse_args()

    ctx = prepare(args.source)
    buttons = button_points(ctx)
    print(f"proc {ctx['w']}x{ctx['h']} buttons {len(buttons)}")

    mobile_pts = sample_profile(ctx, step=10, blueprint_step=18, buttons=buttons)
    desktop_pts = sample_profile(ctx, step=6, blueprint_step=12, buttons=buttons)
    from collections import Counter

    print(f"mobile {len(mobile_pts)} {Counter(p[2] for p in mobile_pts)}")
    print(f"desktop {len(desktop_pts)} {Counter(p[2] for p in desktop_pts)}")

    mobile_raw = pack_points(mobile_pts)
    desktop_raw = pack_points(desktop_pts)
    write_js(args.out, mobile_raw, desktop_raw)

    if args.preview_dir:
        args.preview_dir.mkdir(parents=True, exist_ok=True)
        render_preview(desktop_pts, (1440, 860), False, args.preview_dir / "dots-desktop.jpg")
        render_preview(desktop_pts, (1440, 860), False, args.preview_dir / "dots-desktop-bare.jpg", veil=False)
        render_preview(mobile_pts, (390, 640), True, args.preview_dir / "dots-mobile.jpg")
        render_preview(mobile_pts, (390, 700), True, args.preview_dir / "dots-mobile-bare.jpg", veil=False)
        # Mask debug, scaled up.
        h, w = ctx["h"], ctx["w"]
        mask = np.zeros((h, w, 3), dtype=np.uint8)
        mask[ctx["blue"]] = (20, 40, 60)
        mask[ctx["person"]] = (140, 130, 110)
        mask[ctx["console"]] = (40, 40, 48)
        Image.fromarray(mask).resize((900, int(900 * h / w)), Image.Resampling.NEAREST).save(
            args.preview_dir / "mask.png"
        )


if __name__ == "__main__":
    main()
