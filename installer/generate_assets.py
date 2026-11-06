#!/usr/bin/env python3
"""
Studio-Grade Multi-Resolution Windows Icon & Installer Banner Generator.
Generates crisp, modern gradient icons visible on both Windows 11 Dark & Light themes:
  - assets/videostudio.ico (16, 24, 32, 48, 64, 128, 256 px)
  - assets/videostudio_preview.png (256 px PNG)
  - src/ui/logo.png & src/ui/favicon.ico (for top header & WebView)
  - assets/wizard_banner.bmp & assets/wizard_small.bmp (Inno Setup 6)
"""
from __future__ import annotations

import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
UI_DIR = ROOT / "src" / "ui"


def _draw_logo_canvas(size: int) -> Image.Image:
    ss = 4
    S = size * ss
    pad = max(4, int(S * 0.045))
    rad = int(S * 0.235)

    # 1. Smooth diagonal gradient background (#06B6D4 -> #4F46E5 -> #7C3AED)
    grad = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    px = grad.load()
    span = max(1, (S - 2 * pad) * 2)
    for y in range(pad, S - pad):
        for x in range(pad, S - pad):
            t = ((x - pad) + (y - pad)) / span
            if t < 0.5:
                u = t * 2.0
                r = int(14 + u * (79 - 14))
                g = int(165 + u * (70 - 165))
                b = int(233 + u * (229 - 233))
            else:
                u = (t - 0.5) * 2.0
                r = int(79 + u * (124 - 79))
                g = int(70 + u * (58 - 70))
                b = int(229 + u * (237 - 229))
            px[x, y] = (r, g, b, 255)

    mask = Image.new("L", (S, S), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((pad, pad, S - pad - 1, S - pad - 1), radius=rad, fill=255)

    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    canvas.paste(grad, (0, 0), mask)

    # 2. Luminous outer glass border so it stands out on pitch-black Windows 11 taskbars
    bd = ImageDraw.Draw(canvas)
    rim_w = max(4, int(S * 0.026))
    bd.rounded_rectangle(
        (pad, pad, S - pad - 1, S - pad - 1),
        radius=rad,
        outline=(125, 211, 252, 235),
        width=rim_w,
    )

    # 3. Soft dark drop-shadow behind central Play emblem
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    cx, cy = S // 2, S // 2
    tri_w = int(S * 0.34)
    tri_h = int(S * 0.38)
    off_x = int(S * 0.035)
    pts_shadow = [
        (cx - tri_w // 2 + off_x, cy - tri_h // 2 + int(S * 0.025)),
        (cx - tri_w // 2 + off_x, cy + tri_h // 2 + int(S * 0.025)),
        (cx + tri_w // 2 + off_x, cy + int(S * 0.025)),
    ]
    sd.polygon(pts_shadow, fill=(7, 11, 20, 155))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(2, int(S * 0.028))))
    canvas = Image.alpha_composite(canvas, shadow)

    # 4. Crisp pure-white Play emblem + golden/cyan AI spark star at top-right
    fg = ImageDraw.Draw(canvas)
    pts = [
        (cx - tri_w // 2 + off_x, cy - tri_h // 2),
        (cx - tri_w // 2 + off_x, cy + tri_h // 2),
        (cx + tri_w // 2 + off_x, cy),
    ]
    fg.polygon(pts, fill=(255, 255, 255, 255))

    # 4-point AI spark in top-right corner
    sx, sy = int(S * 0.74), int(S * 0.26)
    sr = int(S * 0.075)
    ri = max(2, int(sr * 0.28))
    spark_pts = [
        (sx, sy - sr),
        (sx + ri, sy - ri),
        (sx + sr, sy),
        (sx + ri, sy + ri),
        (sx, sy + sr),
        (sx - ri, sy + ri),
        (sx - sr, sy),
        (sx - ri, sy - ri),
    ]
    fg.polygon(spark_pts, fill=(254, 240, 138, 255))

    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def generate_all_assets() -> dict[str, str]:
    ASSETS.mkdir(parents=True, exist_ok=True)
    ico_path = ASSETS / "videostudio.ico"
    png_path = ASSETS / "videostudio_preview.png"

    icon_256 = _draw_logo_canvas(256)
    icon_256.save(png_path, format="PNG")
    icon_256.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    if UI_DIR.exists():
        shutil.copy2(png_path, UI_DIR / "logo.png")
        shutil.copy2(ico_path, UI_DIR / "favicon.ico")

    # Inno Setup Wizard Banner (164x314, 24-bit BMP)
    banner = Image.new("RGB", (164, 314), (9, 14, 26))
    bd = ImageDraw.Draw(banner)
    for y in range(314):
        r = int(9 + (y / 314) * 26)
        g = int(14 + (y / 314) * 22)
        b = int(26 + (y / 314) * 68)
        bd.line([(0, y), (164, y)], fill=(r, g, b))
    logo_92 = _draw_logo_canvas(92)
    banner.paste(logo_92, (36, 84), logo_92)
    banner_path = ASSETS / "wizard_banner.bmp"
    banner.save(banner_path, format="BMP")

    # Inno Setup Small Image (55x55, 24-bit BMP)
    small = Image.new("RGB", (55, 55), (15, 22, 38))
    logo_44 = _draw_logo_canvas(44)
    small.paste(logo_44, (5, 5), logo_44)
    small_path = ASSETS / "wizard_small.bmp"
    small.save(small_path, format="BMP")

    return {
        "ico": str(ico_path),
        "png": str(png_path),
        "banner": str(banner_path),
        "small": str(small_path),
    }


if __name__ == "__main__":
    out = generate_all_assets()
    print("Assets generados:", out)
