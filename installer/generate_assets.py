#!/usr/bin/env python3
"""
Programmatic High-DPI Brand Asset Generator for VideoStudio Windows Installer.
Generates:
  - assets/videostudio.ico (16, 32, 48, 64, 128, 256 px)
  - assets/wizard_banner.bmp (164 x 314 Inno Setup Welcome Banner)
  - assets/wizard_small.bmp (55 x 55 Inno Setup Header Logo)
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def _draw_logo_canvas(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(2, int(size * 0.06))
    rad = int(size * 0.24)

    # Deep studio gradient-like layered rounded rect
    d.rounded_rectangle((pad, pad, size - pad, size - pad), radius=rad, fill=(17, 24, 39, 255))
    inner = pad + max(2, int(size * 0.05))
    d.rounded_rectangle((inner, inner, size - inner, size - inner), radius=max(4, rad - 4), fill=(79, 70, 229, 255))

    # Accent cyan glow corner
    glow_r = int(size * 0.34)
    d.ellipse((size - inner - glow_r, inner, size - inner, inner + glow_r), fill=(6, 182, 212, 165))

    # Crisp white Play prism
    cx, cy = size // 2, size // 2
    tri_w = int(size * 0.28)
    tri_h = int(size * 0.32)
    pts = [
        (cx - tri_w // 2 + int(size * 0.03), cy - tri_h // 2),
        (cx - tri_w // 2 + int(size * 0.03), cy + tri_h // 2),
        (cx + tri_w // 2 + int(size * 0.05), cy),
    ]
    d.polygon(pts, fill=(255, 255, 255, 255))
    return img


def generate_all_assets() -> dict[str, str]:
    ASSETS.mkdir(parents=True, exist_ok=True)
    ico_path = ASSETS / "videostudio.ico"
    base_256 = _draw_logo_canvas(256)
    base_256.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    # Inno Setup Wizard Banner (164x314, 24-bit BMP)
    banner = Image.new("RGB", (164, 314), (9, 13, 22))
    bd = ImageDraw.Draw(banner)
    for y in range(314):
        r = int(9 + (y / 314) * 22)
        g = int(13 + (y / 314) * 20)
        b = int(26 + (y / 314) * 58)
        bd.line([(0, y), (164, y)], fill=(r, g, b))
    logo_96 = _draw_logo_canvas(96)
    banner.paste(logo_96, (34, 64), logo_96)
    bd.rounded_rectangle((24, 184, 140, 208), radius=10, fill=(16, 185, 129))
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
        "banner": str(banner_path),
        "small": str(small_path),
    }


if __name__ == "__main__":
    out = generate_all_assets()
    print("Assets generados:", out)
