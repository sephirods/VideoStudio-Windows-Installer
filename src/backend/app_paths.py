#!/usr/bin/env python3
"""
Application Path & Safe Workspace Manager for VideoStudio Windows Edition.

Ensures strict separation between:
  1. Immutable application binaries & CLI scripts (<InstallDir>/bin, <InstallDir>/cli_engine)
  2. Persistent user data (%APPDATA%/VideoStudio) so 1-click .exe updates NEVER overwrite
     channels, DPAPI-encrypted AI keys, social login sessions, 30-day history, or videos.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

SYNC_ENGINE_ITEMS = (
    "AGENTS.md",
    "SETUP_ONBOARDING.md",
    "requirements.txt",
    "config/channels.example.json",
    "scripts",
    ".agents",
)

IGNORE_DIRS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"}


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_python_script_cmd(script_path: str | Path, *args: str) -> list[str]:
    """Builds a subprocess command to execute a CLI Python script in both dev and PyInstaller frozen modes."""
    if is_frozen():
        return [sys.executable, "--run-script", str(script_path), *[str(a) for a in args]]
    return [sys.executable, str(script_path), *[str(a) for a in args]]


def get_install_root() -> Path:
    """Directory containing VideoStudio.exe (installed) or repository root (dev)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def get_resource_root() -> Path:
    """Directory containing bundled PyInstaller assets (src/ui, src/version.json)."""
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return Path(__file__).resolve().parents[2]


def get_appdata_dir() -> Path:
    """Persistent user directory (%APPDATA%/VideoStudio) safe across installer upgrades."""
    override = os.environ.get("VIDEOSTUDIO_APPDATA_DIR")
    if override:
        base = Path(override).resolve()
    else:
        roaming = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        base = Path(roaming) / "VideoStudio"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_workspace_dir() -> Path:
    """Active CLI runtime workspace inside %APPDATA%/VideoStudio/workspace."""
    ws = get_appdata_dir() / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def get_settings_file() -> Path:
    return get_appdata_dir() / "app_settings.json"


def get_version_info() -> dict:
    candidates = [
        get_resource_root() / "src" / "version.json",
        get_install_root() / "src" / "version.json",
        get_install_root() / "version.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {
        "app_name": "VideoStudio Pro",
        "edition": "Windows Offline All-in-One",
        "version": "1.0.0",
        "github_repo": "sephirods/VideoStudio-Windows-Installer",
        "release_channel": "stable",
        "installer_asset_keyword": "Setup",
    }


def locate_cli_engine_source() -> Path | None:
    """Finds bundled cli_engine/ (installed) or sibling CLI repo (dev)."""
    install_root = get_install_root()
    candidates = [
        install_root / "cli_engine",
        get_resource_root() / "cli_engine",
        install_root.parent / "cli",
        Path(r"C:\ganar dinero"),
        Path(r"C:\VideoStudio\cli"),
    ]
    for c in candidates:
        if (c / "scripts" / "run_pipeline_job.py").exists():
            return c
    return None


def configure_bundled_binaries_path() -> dict:
    """Prepends bundled Offline bin/ (ffmpeg.exe, ffprobe.exe) to process PATH."""
    install_root = get_install_root()
    bin_candidates = [
        install_root / "bin",
        get_resource_root() / "bin",
    ]
    activated_bin = None
    for b in bin_candidates:
        if (b / "ffmpeg.exe").exists():
            activated_bin = str(b)
            current_path = os.environ.get("PATH", "")
            parts = current_path.split(os.pathsep) if current_path else []
            if activated_bin not in parts:
                os.environ["PATH"] = activated_bin + os.pathsep + current_path
            break

    ffmpeg_resolved = shutil.which("ffmpeg")
    ffprobe_resolved = shutil.which("ffprobe")
    return {
        "bundled_bin_dir": activated_bin,
        "ffmpeg_path": ffmpeg_resolved,
        "ffprobe_path": ffprobe_resolved,
        "offline_bundled": bool(activated_bin and ffmpeg_resolved and ffmpeg_resolved.startswith(activated_bin)),
    }


def _copy_tree_filtered(src: Path, dst: Path) -> int:
    copied = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        rel = Path(root).relative_to(src)
        target_dir = dst / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for fname in files:
            if fname.endswith((".pyc", ".pyo")):
                continue
            s_file = Path(root) / fname
            d_file = target_dir / fname
            if not d_file.exists() or s_file.stat().st_size != d_file.stat().st_size or int(s_file.stat().st_mtime) != int(d_file.stat().st_mtime):
                shutil.copy2(s_file, d_file)
                copied += 1
    return copied


def bootstrap_workspace(force_sync: bool = False) -> dict:
    """
    Initializes %APPDATA%/VideoStudio/workspace:
      - Syncs scripts/, .agents/, templates from cli_engine without touching user configs.
      - Ensures config/, config/sessions/, config/history/, storage/cache_videos/, videos/publicaciones/ exist.
    """
    bin_status = configure_bundled_binaries_path()
    ws = get_workspace_dir()
    for sub in (
        "config",
        "config/sessions",
        "config/history",
        "storage/cache_videos",
        "pipeline_runs",
        "videos/publicaciones",
    ):
        (ws / sub).mkdir(parents=True, exist_ok=True)

    ver = get_version_info().get("version", "1.0.0")
    stamp_file = ws / ".engine_version"
    src_engine = locate_cli_engine_source()
    synced_files = 0

    needs_sync = force_sync or not (ws / "scripts" / "run_pipeline_job.py").exists()
    if stamp_file.exists() and stamp_file.read_text(encoding="utf-8").strip() != ver:
        needs_sync = True

    if src_engine and (needs_sync or not is_frozen()):
        for rel_item in SYNC_ENGINE_ITEMS:
            s_path = src_engine / rel_item
            d_path = ws / rel_item
            if not s_path.exists():
                continue
            if s_path.is_dir():
                synced_files += _copy_tree_filtered(s_path, d_path)
            else:
                d_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s_path, d_path)
                synced_files += 1
        stamp_file.write_text(ver, encoding="utf-8")

    return {
        "appdata_dir": str(get_appdata_dir()),
        "workspace_dir": str(ws),
        "engine_source": str(src_engine) if src_engine else None,
        "synced_files": synced_files,
        "binaries": bin_status,
    }


def load_app_settings() -> dict:
    ver = get_version_info()
    defaults = {
        "wizard_completed": False,
        "github_repo": ver.get("github_repo", "sephirods/VideoStudio-Windows-Installer"),
        "production_mode": "auto",  # "auto" (100% unattended) or "copilot" (pause on script/grid)
        "model_profile": "balanced",  # "free", "balanced", "pro", "custom"
        "stage_models": {},
        "auto_check_updates": True,
        "minimize_to_tray": True,
    }
    p = get_settings_file()
    if p.exists():
        try:
            saved = json.loads(p.read_text(encoding="utf-8"))
            defaults.update(saved)
        except Exception:
            pass
    return defaults


def save_app_settings(updates: dict) -> dict:
    current = load_app_settings()
    current.update(updates)
    p = get_settings_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    return current


def detect_legacy_cli_state() -> dict:
    """Checks if an existing CLI workspace on this PC already has stock keys or channels."""
    candidates = [Path(r"C:\ganar dinero"), Path(r"C:\VideoStudio\cli")]
    found = {"has_legacy": False, "source": None, "channels_count": 0, "has_stock_keys": False}
    for base in candidates:
        ch_file = base / "config" / "channels.json"
        st_file = base / "config" / "stock_credentials.json"
        ch_count = 0
        has_stock = False
        if ch_file.exists():
            try:
                data = json.loads(ch_file.read_text(encoding="utf-8"))
                ch_count = len(data.get("channels", {}))
            except Exception:
                pass
        if st_file.exists():
            try:
                sdata = json.loads(st_file.read_text(encoding="utf-8"))
                has_stock = bool(sdata.get("pixabay_api_keys") or sdata.get("pexels_api_keys"))
            except Exception:
                pass
        if ch_count > 0 or has_stock:
            return {
                "has_legacy": True,
                "source": str(base),
                "channels_count": ch_count,
                "has_stock_keys": has_stock,
            }
    return found


def import_legacy_cli_state() -> dict:
    """Copies channels, stock credentials, sessions, and 30d history from legacy CLI workspace."""
    info = detect_legacy_cli_state()
    if not info["has_legacy"] or not info["source"]:
        return {"imported": False, "reason": "No se detectó configuración previa."}
    src = Path(info["source"]) / "config"
    dst = get_workspace_dir() / "config"
    imported_items = []
    for fname in ("channels.json", "stock_credentials.json"):
        if (src / fname).exists():
            shutil.copy2(src / fname, dst / fname)
            imported_items.append(fname)
    for dname in ("history", "sessions"):
        if (src / dname).exists():
            _copy_tree_filtered(src / dname, dst / dname)
            imported_items.append(dname)
    return {"imported": True, "source": info["source"], "items": imported_items}
