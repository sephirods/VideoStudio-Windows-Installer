#!/usr/bin/env python3
"""
Hardware Doctor, Stock API Tester & 1.5 GB LRU Cache Monitor.
Runs silently without spawning black console windows on Windows.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

from src.backend.app_paths import configure_bundled_binaries_path, get_workspace_dir

NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
LRU_CAP_MB = 1500.0


def detect_gpu_and_ffmpeg() -> dict:
    bin_info = configure_bundled_binaries_path()
    cpu_cores = os.cpu_count() or 4
    hardware_type = "cpu"
    gpu_name = "CPU Multihilo"
    gpu_vram_mb = 0
    video_encoder = "libx264"
    preset = "fast"
    concurrency = 2 if cpu_cores >= 8 else 1

    # 1. Check NVIDIA GPU
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=NO_WINDOW,
        )
        if res.returncode == 0 and res.stdout.strip():
            first = res.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in first.split(",")]
            gpu_name = parts[0]
            if len(parts) > 1 and parts[1].isdigit():
                gpu_vram_mb = int(parts[1])
            hardware_type = "nvidia"
            video_encoder = "h264_nvenc"
            preset = "p4"
            concurrency = 5 if gpu_vram_mb >= 16000 else (4 if gpu_vram_mb >= 8000 else 2)
    except Exception:
        pass

    # 2. Inspect FFmpeg capabilities
    ffmpeg_ok = False
    ffmpeg_version = "No detectado"
    has_libass = False
    has_nvenc = False
    ffmpeg_bin = bin_info.get("ffmpeg_path") or "ffmpeg"
    try:
        vres = subprocess.run(
            [ffmpeg_bin, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=NO_WINDOW,
        )
        if vres.returncode == 0:
            ffmpeg_ok = True
            first_line = vres.stdout.splitlines()[0] if vres.stdout else ""
            ffmpeg_version = first_line.replace("ffmpeg version ", "").split(" Copyright")[0].strip()
            has_libass = "--enable-libass" in vres.stdout

        eres = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=NO_WINDOW,
        )
        if eres.returncode == 0:
            has_nvenc = "h264_nvenc" in eres.stdout
            if hardware_type == "cpu" and "h264_amf" in eres.stdout:
                hardware_type = "amd"
                gpu_name = "AMD Radeon (AMF)"
                video_encoder = "h264_amf"
                preset = "speed"
                concurrency = 2
            elif hardware_type == "nvidia" and not has_nvenc:
                video_encoder = "libx264"
                preset = "fast"
    except Exception:
        pass

    ws = get_workspace_dir()
    disk = shutil.disk_usage(ws)
    free_gb = round(disk.free / (1024 ** 3), 1)

    hw_payload = {
        "hardware_type": hardware_type,
        "gpu_name": gpu_name,
        "gpu_vram_mb": gpu_vram_mb,
        "cpu_cores": cpu_cores,
        "video_encoder": video_encoder,
        "max_concurrency": concurrency,
        "ffmpeg_preset": preset,
        "ffmpeg_ok": ffmpeg_ok,
        "ffmpeg_version": ffmpeg_version,
        "ffmpeg_offline_bundled": bin_info.get("offline_bundled", False),
        "ffmpeg_path": bin_info.get("ffmpeg_path"),
        "has_libass": has_libass,
        "has_nvenc": has_nvenc,
        "disk_free_gb": free_gb,
        "status": "ready" if ffmpeg_ok else "missing_ffmpeg",
    }

    hw_file = ws / "config" / "hardware.json"
    hw_file.parent.mkdir(parents=True, exist_ok=True)
    hw_file.write_text(json.dumps(hw_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return hw_payload


def get_stock_credentials_status() -> dict:
    ws = get_workspace_dir()
    st_file = ws / "config" / "stock_credentials.json"
    data = {"provider_mode": "both", "pixabay_api_keys": [], "pexels_api_keys": []}
    if st_file.exists():
        try:
            data.update(json.loads(st_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    pix = data.get("pixabay_api_keys", [])
    pex = data.get("pexels_api_keys", [])
    return {
        "provider_mode": data.get("provider_mode", "both"),
        "has_pixabay": bool(pix),
        "has_pexels": bool(pex),
        "pixabay_masked": f"{pix[0][:5]}...{pix[0][-4:]}" if pix and len(pix[0]) > 9 else ("Activa" if pix else ""),
        "pexels_masked": f"{pex[0][:5]}...{pex[0][-4:]}" if pex and len(pex[0]) > 9 else ("Activa" if pex else ""),
    }


async def test_and_save_stock_keys(pixabay_key: str = "", pexels_key: str = "", provider_mode: str = "both") -> dict:
    ws = get_workspace_dir()
    st_file = ws / "config" / "stock_credentials.json"
    existing = {"provider_mode": provider_mode, "pixabay_api_keys": [], "pexels_api_keys": []}
    if st_file.exists():
        try:
            existing.update(json.loads(st_file.read_text(encoding="utf-8")))
        except Exception:
            pass

    results = {"pixabay": {"tested": False, "ok": False, "message": ""}, "pexels": {"tested": False, "ok": False, "message": ""}}

    async with httpx.AsyncClient(timeout=8.0) as client:
        if pixabay_key and not pixabay_key.startswith("KEEP_EXISTING"):
            results["pixabay"]["tested"] = True
            try:
                r = await client.get("https://pixabay.com/api/", params={"key": pixabay_key.strip(), "q": "nature", "per_page": 3})
                if r.status_code == 200:
                    results["pixabay"]["ok"] = True
                    results["pixabay"]["message"] = "Clave Pixabay verificada correctamente."
                    existing["pixabay_api_keys"] = [pixabay_key.strip()]
                else:
                    results["pixabay"]["message"] = f"Pixabay rechazó la clave (HTTP {r.status_code})."
            except Exception as e:
                results["pixabay"]["message"] = f"Error de red probando Pixabay: {e}"

        if pexels_key and not pexels_key.startswith("KEEP_EXISTING"):
            results["pexels"]["tested"] = True
            try:
                r = await client.get(
                    "https://api.pexels.com/videos/popular",
                    params={"per_page": 1},
                    headers={"Authorization": pexels_key.strip()},
                )
                if r.status_code == 200:
                    results["pexels"]["ok"] = True
                    results["pexels"]["message"] = "Clave Pexels 4K verificada correctamente."
                    existing["pexels_api_keys"] = [pexels_key.strip()]
                else:
                    results["pexels"]["message"] = f"Pexels rechazó la clave (HTTP {r.status_code})."
            except Exception as e:
                results["pexels"]["message"] = f"Error de red probando Pexels: {e}"

    existing["provider_mode"] = provider_mode
    st_file.parent.mkdir(parents=True, exist_ok=True)
    st_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": get_stock_credentials_status(), "validation": results}


def get_cache_health() -> dict:
    ws = get_workspace_dir()
    cache_dir = ws / "storage" / "cache_videos"
    cache_dir.mkdir(parents=True, exist_ok=True)
    files = [p for p in cache_dir.rglob("*") if p.is_file()]
    total_bytes = sum(p.stat().st_size for p in files)
    used_mb = round(total_bytes / (1024 * 1024), 2)
    pct = min(100.0, round((used_mb / LRU_CAP_MB) * 100.0, 1))
    return {
        "cache_dir": str(cache_dir),
        "files_count": len(files),
        "used_mb": used_mb,
        "cap_mb": LRU_CAP_MB,
        "percent": pct,
        "healthy": used_mb <= LRU_CAP_MB,
    }


def purge_video_cache(keep_mb: float = 0.0) -> dict:
    """Purges LRU video cache down to keep_mb (0 MB = full clean, or 1500 MB LRU cap)."""
    ws = get_workspace_dir()
    cache_dir = ws / "storage" / "cache_videos"
    if not cache_dir.exists():
        return {"freed_mb": 0.0, "remaining_mb": 0.0, "deleted_files": 0}

    files = [p for p in cache_dir.rglob("*") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime)  # Oldest first (LRU)
    total_bytes = sum(p.stat().st_size for p in files)
    cap_bytes = int(keep_mb * 1024 * 1024)
    freed = 0
    deleted = 0

    for f in files:
        if total_bytes <= cap_bytes:
            break
        try:
            sz = f.stat().st_size
            f.unlink()
            total_bytes -= sz
            freed += sz
            deleted += 1
        except Exception:
            pass

    return {
        "freed_mb": round(freed / (1024 * 1024), 2),
        "remaining_mb": round(total_bytes / (1024 * 1024), 2),
        "deleted_files": deleted,
        "updated_health": get_cache_health(),
    }
