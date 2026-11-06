#!/usr/bin/env python3
"""
1-Click GitHub Releases Auto-Updater for VideoStudio Windows Edition.

Features:
  - Tolerates uncreated GitHub repos / zero releases cleanly (HTTP 404 -> 'repo_pending', zero errors).
  - Semantic version comparison (e.g. v1.1.0 > v1.0.0).
  - Streams new Setup .exe with real-time MB/s and % progress.
  - Verifies Windows PE 'MZ' header + SHA-256 checksum (if SHA256SUMS.txt is attached to the release).
  - Launches Inno Setup installer in seamless upgrade mode (/SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS)
    while %APPDATA%/VideoStudio keeps all channels, API keys, and sessions 100% intact.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any

import httpx

from src.backend.app_paths import get_version_info, load_app_settings

_UPDATE_STATE: dict[str, Any] = {
    "status": "idle",  # idle | checking | repo_pending | up_to_date | update_available | downloading | ready_to_install | installing | error
    "current_version": "1.0.0",
    "latest_version": None,
    "github_repo": "",
    "update_available": False,
    "release_name": "",
    "release_notes": "",
    "published_at": "",
    "asset_name": "",
    "asset_size_mb": 0.0,
    "download_url": "",
    "sha256_url": "",
    "progress_percent": 0.0,
    "downloaded_mb": 0.0,
    "speed_mbps": 0.0,
    "downloaded_installer_path": "",
    "sha256_verified": False,
    "message": "Sin comprobar aún",
    "error": None,
}


def parse_semver(ver_str: str) -> tuple[int, int, int]:
    cleaned = re.sub(r"^[^0-9]*", "", (ver_str or "0.0.0").strip())
    core = cleaned.split("-")[0].split("+")[0]
    parts = core.split(".")
    nums = []
    for i in range(3):
        try:
            nums.append(int(parts[i]))
        except Exception:
            nums.append(0)
    return (nums[0], nums[1], nums[2])


def is_newer_version(remote_ver: str, local_ver: str) -> bool:
    return parse_semver(remote_ver) > parse_semver(local_ver)


def get_updater_state() -> dict[str, Any]:
    ver = get_version_info()
    settings = load_app_settings()
    _UPDATE_STATE["current_version"] = ver.get("version", "1.0.0")
    _UPDATE_STATE["github_repo"] = settings.get("github_repo") or ver.get("github_repo", "sephirods/VideoStudio-Windows-Installer")
    return dict(_UPDATE_STATE)


async def check_for_updates(custom_api_url: str | None = None) -> dict[str, Any]:
    ver_info = get_version_info()
    settings = load_app_settings()
    current_ver = ver_info.get("version", "1.0.0")
    repo = (settings.get("github_repo") or ver_info.get("github_repo") or "").strip().strip("/")

    _UPDATE_STATE.update({
        "status": "checking",
        "current_version": current_ver,
        "github_repo": repo,
        "error": None,
        "message": "Buscando actualizaciones en GitHub...",
    })

    if not repo or "/" not in repo:
        _UPDATE_STATE.update({
            "status": "repo_pending",
            "update_available": False,
            "message": f"v{current_ver} · Configura tu repo Git cuando lo crees",
        })
        return dict(_UPDATE_STATE)

    api_url = custom_api_url or os.environ.get("VIDEOSTUDIO_UPDATE_API_URL") or f"https://api.github.com/repos/{repo}/releases/latest"

    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            r = await client.get(
                api_url,
                headers={"Accept": "application/vnd.github+json", "User-Agent": f"VideoStudioPro/{current_ver}"},
            )

        if r.status_code == 404:
            # Expected cleanly when the Git repo or first GitHub Release is not published yet!
            _UPDATE_STATE.update({
                "status": "repo_pending",
                "update_available": False,
                "latest_version": current_ver,
                "message": f"v{current_ver} · Canal Git listo (esperando 1er Release)",
                "error": None,
            })
            return dict(_UPDATE_STATE)

        r.raise_for_status()
        rel = r.json()
        tag_name = rel.get("tag_name") or rel.get("name") or ""
        clean_remote = tag_name.lstrip("vV").strip() or current_ver
        assets = rel.get("assets") or []

        exe_asset = None
        sha_asset = None
        keyword = ver_info.get("installer_asset_keyword", "Setup").lower()
        for a in assets:
            aname = a.get("name", "")
            low = aname.lower()
            if low.endswith(".exe"):
                if keyword in low or exe_asset is None:
                    exe_asset = a
            elif "sha256" in low or low.endswith(".sha256") or low == "checksums.txt":
                sha_asset = a

        if is_newer_version(clean_remote, current_ver) and exe_asset:
            sz_mb = round(int(exe_asset.get("size") or 0) / (1024 * 1024), 2)
            _UPDATE_STATE.update({
                "status": "update_available",
                "latest_version": clean_remote,
                "update_available": True,
                "release_name": rel.get("name") or f"v{clean_remote}",
                "release_notes": (rel.get("body") or "Mejoras de rendimiento y estabilidad.")[:1200],
                "published_at": rel.get("published_at") or "",
                "asset_name": exe_asset.get("name", f"VideoStudio-Setup-v{clean_remote}.exe"),
                "asset_size_mb": sz_mb,
                "download_url": exe_asset.get("browser_download_url", ""),
                "sha256_url": sha_asset.get("browser_download_url", "") if sha_asset else "",
                "message": f"Nueva versión v{clean_remote} disponible ({sz_mb} MB)",
                "error": None,
            })
        else:
            _UPDATE_STATE.update({
                "status": "up_to_date",
                "latest_version": clean_remote,
                "update_available": False,
                "message": f"v{current_ver} · Estás en la última versión",
                "error": None,
            })
    except Exception as e:
        _UPDATE_STATE.update({
            "status": "error",
            "update_available": False,
            "message": f"v{current_ver} · Sin conexión al servidor de actualizaciones",
            "error": str(e)[:160],
        })

    return dict(_UPDATE_STATE)


async def download_update_installer(target_dir: Path | None = None) -> dict[str, Any]:
    url = _UPDATE_STATE.get("download_url", "")
    asset_name = _UPDATE_STATE.get("asset_name") or "VideoStudio-Setup-Update.exe"
    if not url:
        return {"ok": False, "error": "No hay URL de actualización pendiente."}

    out_dir = target_dir or (Path(tempfile.gettempdir()) / "VideoStudioUpdates")
    out_dir.mkdir(parents=True, exist_ok=True)
    dest_file = out_dir / asset_name

    _UPDATE_STATE.update({
        "status": "downloading",
        "progress_percent": 0.0,
        "downloaded_mb": 0.0,
        "speed_mbps": 0.0,
        "sha256_verified": False,
        "message": f"Descargando {asset_name}...",
        "error": None,
    })

    hasher = hashlib.sha256()
    t0 = time.time()
    downloaded = 0

    try:
        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
            expected_sha = None
            sha_url = _UPDATE_STATE.get("sha256_url")
            if sha_url:
                sr = await client.get(sha_url)
                if sr.status_code == 200:
                    for line in sr.text.splitlines():
                        if asset_name in line or len(line.strip().split()) == 1:
                            token = line.strip().split()[0].lower()
                            if re.fullmatch(r"[0-9a-f]{64}", token):
                                expected_sha = token
                                break

            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length") or 0)
                with open(dest_file, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=131072):
                        f.write(chunk)
                        hasher.update(chunk)
                        downloaded += len(chunk)
                        elapsed = max(0.05, time.time() - t0)
                        dl_mb = downloaded / (1024 * 1024)
                        pct = (downloaded / total * 100.0) if total > 0 else 50.0
                        _UPDATE_STATE.update({
                            "downloaded_mb": round(dl_mb, 2),
                            "progress_percent": round(min(99.9, pct), 1),
                            "speed_mbps": round(dl_mb / elapsed, 2),
                        })

        # Verify valid Windows PE executable ('MZ' magic bytes)
        with open(dest_file, "rb") as f:
            magic = f.read(2)
        if magic != b"MZ":
            dest_file.unlink(missing_ok=True)
            raise ValueError("El archivo descargado no es un ejecutable válido de Windows (PE MZ).")

        actual_sha = hasher.hexdigest().lower()
        if expected_sha and actual_sha != expected_sha:
            dest_file.unlink(missing_ok=True)
            raise ValueError(f"Checksum SHA-256 inválido (esperado {expected_sha[:12]}..., recibido {actual_sha[:12]}...).")

        _UPDATE_STATE.update({
            "status": "ready_to_install",
            "progress_percent": 100.0,
            "downloaded_installer_path": str(dest_file),
            "sha256_verified": bool(expected_sha),
            "message": f"Descarga completa ({_UPDATE_STATE['downloaded_mb']} MB). Lista para instalar.",
        })
        return {"ok": True, "installer_path": str(dest_file), "sha256": actual_sha, "state": dict(_UPDATE_STATE)}
    except Exception as e:
        _UPDATE_STATE.update({
            "status": "error",
            "error": str(e),
            "message": f"Error al descargar actualización: {e}",
        })
        return {"ok": False, "error": str(e), "state": dict(_UPDATE_STATE)}


def trigger_installer_and_exit(silent: bool = True, dry_run: bool = False) -> dict[str, Any]:
    """Spawns the downloaded Inno Setup installer to upgrade in-place and schedules clean app exit."""
    installer_str = _UPDATE_STATE.get("downloaded_installer_path", "")
    if not installer_str or not Path(installer_str).exists():
        return {"ok": False, "error": "No se encontró el instalador descargado en disco."}

    args = [installer_str]
    if silent:
        args.extend(["/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"])

    _UPDATE_STATE.update({
        "status": "installing",
        "message": "Iniciando instalador de nueva versión...",
    })

    if dry_run:
        return {"ok": True, "dry_run": True, "command": args}

    creation_flags = 0
    if sys.platform.startswith("win"):
        creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    subprocess.Popen(args, close_fds=True, creationflags=creation_flags)
    return {"ok": True, "launched": True, "command": args}
