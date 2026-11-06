#!/usr/bin/env python3
"""
1-Command Offline All-in-One Windows Installer Builder (`VideoStudio-Setup-vX.Y.Z.exe`).

Steps:
  1. Generates brand .ico & .bmp installer art (`assets/`).
  2. Stages real `ffmpeg.exe` & `ffprobe.exe` (resolving WinGet symlinks) into `build/staging/bin/`.
  3. Stages clean 9-subagent CLI engine (`scripts/`, `.agents/`, templates) into `build/staging/cli_engine/`.
  4. Runs PyInstaller (`--onedir --windowed`) bundling `google.antigravity` (`localharness.exe`), FastAPI, WebView2, Edge-TTS, Playwright, yt-dlp.
  5. Compiles `Output/VideoStudio-Setup-vX.Y.Z.exe` via Inno Setup 6 (`ISCC.exe`) and writes `Output/SHA256SUMS.txt` for 1-click GitHub Auto-Updates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from installer.generate_assets import generate_all_assets  # noqa: E402

CLI_SYNC_ITEMS = (
    "AGENTS.md",
    "SETUP_ONBOARDING.md",
    "requirements.txt",
    "config/channels.example.json",
    "scripts",
    ".agents",
)

IGNORE_DIRS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"}


def _resolve_real_binary(cmd_name: str) -> Path:
    found = shutil.which(cmd_name)
    if not found:
        raise FileNotFoundError(f"No se encontró '{cmd_name}' en PATH para empaquetarlo en el instalador Offline.")
    p = Path(found)
    # Follow Windows / WinGet symlink to actual 100+ MB binary!
    resolved = p.resolve()
    if resolved.exists() and resolved.stat().st_size > 1_000_000:
        return resolved
    # Fallback search in WinGet Packages
    winget_pkgs = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if winget_pkgs.exists():
        matches = list(winget_pkgs.rglob(f"{cmd_name}.exe" if not cmd_name.endswith(".exe") else cmd_name))
        big = [m for m in matches if m.stat().st_size > 1_000_000]
        if big:
            return big[0]
    if p.exists() and p.stat().st_size > 1_000_000:
        return p
    raise RuntimeError(f"El binario '{cmd_name}' resuelto ({resolved}) parece un enlace vacío.")


def _find_cli_repo() -> Path:
    candidates = [
        Path(os.environ.get("VIDEOSTUDIO_CLI_SOURCE", "")) if os.environ.get("VIDEOSTUDIO_CLI_SOURCE") else None,
        ROOT.parent / "cli",
        Path(r"C:\VideoStudio\cli"),
        Path(r"C:\ganar dinero"),
    ]
    for c in candidates:
        if c and (c / "scripts" / "run_pipeline_job.py").exists():
            return c
    raise FileNotFoundError("No se encontró el repositorio hermano CLI (C:\\VideoStudio\\cli o C:\\ganar dinero).")


def _find_iscc() -> Path:
    candidates = [
        shutil.which("ISCC"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return Path(c)
    raise FileNotFoundError("Inno Setup 6 (ISCC.exe) no encontrado. Instálalo con: winget install JRSoftware.InnoSetup")


def _copy_clean(src: Path, dst: Path) -> None:
    if src.is_dir():
        for r, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            rel = Path(r).relative_to(src)
            target = dst / rel
            target.mkdir(parents=True, exist_ok=True)
            for f in files:
                if f.endswith((".pyc", ".pyo")):
                    continue
                shutil.copy2(Path(r) / f, target / f)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_all(skip_pyinstaller: bool = False) -> dict:
    ver_data = json.loads((ROOT / "src" / "version.json").read_text(encoding="utf-8"))
    version = ver_data.get("version", "1.0.0")

    print(f"[1/5] Generando iconos y arte del instalador para VideoStudio Pro v{version}...")
    generate_all_assets()

    staging_dir = ROOT / "build" / "staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    (staging_dir / "bin").mkdir(parents=True, exist_ok=True)
    (staging_dir / "cli_engine").mkdir(parents=True, exist_ok=True)

    print("[2/5] Empaquetando binarios Offline Todo-en-Uno (ffmpeg.exe + ffprobe.exe)...")
    ff_real = _resolve_real_binary("ffmpeg")
    fp_real = _resolve_real_binary("ffprobe")
    shutil.copy2(ff_real, staging_dir / "bin" / "ffmpeg.exe")
    shutil.copy2(fp_real, staging_dir / "bin" / "ffprobe.exe")
    print(f"      -> ffmpeg.exe ({round(ff_real.stat().st_size / 1048576, 1)} MB)")
    print(f"      -> ffprobe.exe ({round(fp_real.stat().st_size / 1048576, 1)} MB)")

    print("[3/5] Sincronizando motor CLI limpio (scripts + 9 subagentes)...")
    cli_src = _find_cli_repo()
    for rel in CLI_SYNC_ITEMS:
        s = cli_src / rel
        if s.exists():
            _copy_clean(s, staging_dir / "cli_engine" / rel)

    if not skip_pyinstaller:
        print("[4/5] Compilando VideoStudio.exe con PyInstaller (incluyendo Antigravity SDK localharness.exe)...")
        pyi_cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--clean",
            "--log-level", "ERROR",
            "--onedir",
            "--windowed",
            "--name", "VideoStudio",
            "--icon", str(ROOT / "assets" / "videostudio.ico"),
            "--paths", str(ROOT),
            "--add-data", f"{ROOT / 'src' / 'ui'};src/ui",
            "--add-data", f"{ROOT / 'src' / 'version.json'};src",
            "--add-data", f"{ROOT / 'assets'};assets",
            "--collect-all", "google.antigravity",
            "--collect-all", "PIL",
            "--collect-all", "pydantic_core",
            "--collect-all", "pydantic",
            "--collect-all", "fastapi",
            "--collect-all", "webview",
            "--collect-submodules", "uvicorn",
            "--collect-submodules", "httpx",
            "--collect-submodules", "httpcore",
            "--collect-submodules", "edge_tts",
            "--collect-submodules", "aiohttp",
            "--collect-submodules", "yt_dlp",
            "--collect-submodules", "playwright",
            "--hidden-import", "PIL.Image",
            "--hidden-import", "PIL.ImageDraw",
            "--hidden-import", "PIL.ImageEnhance",
            "--hidden-import", "PIL.ImageFilter",
            "--hidden-import", "PIL.ImageFont",
            "--hidden-import", "PIL.ImageOps",
            "--hidden-import", "yt_dlp",
            "--hidden-import", "edge_tts",
            "--hidden-import", "playwright.sync_api",
            "--hidden-import", "youtube_comment_downloader",
            "--hidden-import", "xml.etree.ElementTree",
            "--hidden-import", "urllib.request",
            "--hidden-import", "urllib.parse",
            "--hidden-import", "concurrent.futures",
            "--hidden-import", "http.server",
            "--hidden-import", "mimetypes",
            "--hidden-import", "glob",
            "--hidden-import", "platform",
            "--hidden-import", "pystray",
            "--hidden-import", "webview",
            str(ROOT / "src" / "main.py"),
        ]
        subprocess.run(pyi_cmd, cwd=str(ROOT), check=True)

        # Mandatory smoke tests on compiled VideoStudio.exe before packaging installer!
        import tempfile
        with tempfile.TemporaryDirectory(prefix="vs_pyi_smoke_") as tmp_smoke:
            smoke_out = Path(tmp_smoke) / "selftest.txt"
            smoke_gui_out = Path(tmp_smoke) / "smokegui.txt"
            env = os.environ.copy()
            env["VIDEOSTUDIO_APPDATA_DIR"] = str(Path(tmp_smoke) / "appdata")
            env["VIDEOSTUDIO_SELFTEST_FILE"] = str(smoke_out)
            env["VIDEOSTUDIO_SMOKE_GUI_FILE"] = str(smoke_gui_out)
            exe_built = ROOT / "dist" / "VideoStudio" / "VideoStudio.exe"

            # 1) CLI & Bundled Path Self-Test
            res = subprocess.run([str(exe_built), "--self-test"], env=env, capture_output=True, text=True)
            if res.returncode != 0 or not smoke_out.exists():
                raise RuntimeError(f"Smoke test CLI de VideoStudio.exe falló (rc={res.returncode}): {res.stderr}")
            print(f"      -> Smoke Test CLI OK: {smoke_out.read_text(encoding='utf-8')}")

            # 2) Embedded --run-script All-Scripts Import & Zero-CMD-Window Verification!
            verify_script = Path(tmp_smoke) / "verify_embedded_scripts.py"
            ws_scripts = Path(tmp_smoke) / "appdata" / "workspace" / "scripts"
            # Copy staged cli_engine/scripts into smoke workspace so all sibling imports resolve identically to production
            _copy_clean(staging_dir / "cli_engine" / "scripts", ws_scripts)
            verify_script.write_text(
                "import importlib, pathlib, subprocess, sys\n"
                "from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont\n"
                "import edge_tts, yt_dlp, xml.etree.ElementTree\n"
                "assert getattr(subprocess.Popen, '_vs_silent_patched', False), 'Missing silent subprocess patch'\n"
                f"sdir = pathlib.Path(r'{ws_scripts}')\n"
                "sys.path.insert(0, str(sdir))\n"
                "required = [\n"
                "    'fetch_trends_data', 'fetch_viral_intelligence', 'fetch_real_images',\n"
                "    'convert_image_to_clip', 'generate_contact_sheet', 'generate_animated_subtitles',\n"
                "    'create_generic_outro', 'run_pipeline_job', 'run_qa_audit',\n"
                "    'create_viral_thumbnail', 'manage_storage_and_archive', 'content_deduplication',\n"
                "    'detect_hardware', 'connect_account', 'universal_scheduler',\n"
                "]\n"
                "for mod in required:\n"
                "    importlib.import_module(mod)\n"
                "print('EMBEDDED_SCRIPTS_OK count=' + str(len(required)))\n",
                encoding="utf-8",
            )
            res_emb = subprocess.run(
                [str(exe_built), "--run-script", str(verify_script)],
                env=env,
                capture_output=True,
                text=True,
                timeout=25,
            )
            if res_emb.returncode != 0 or "EMBEDDED_SCRIPTS_OK" not in res_emb.stdout:
                raise RuntimeError(
                    f"Smoke test --run-script falló (rc={res_emb.returncode}):\nSTDOUT: {res_emb.stdout}\nSTDERR: {res_emb.stderr}"
                )
            print(f"      -> Smoke Test --run-script (15 scripts + PIL.ImageEnhance + Zero-CMD) OK: {res_emb.stdout.strip()}")

            # 3) Real Windowed Uvicorn + Edge WebView2 Live DOM Boot Test!
            res_gui = subprocess.run([str(exe_built), "--smoke-gui"], env=env, capture_output=True, text=True, timeout=30)
            if res_gui.returncode != 0 or not smoke_gui_out.exists():
                log_f = Path(tmp_smoke) / "appdata" / "logs" / "videostudio.log"
                log_txt = log_f.read_text(encoding="utf-8", errors="replace") if log_f.exists() else res_gui.stderr
                raise RuntimeError(f"Smoke test GUI (--windowed Uvicorn + WebView2) falló (rc={res_gui.returncode}):\n{log_txt}")
            print(f"      -> Smoke Test GUI (Uvicorn + WebView2) OK: {smoke_gui_out.read_text(encoding='utf-8')}")

    print("[5/5] Compilando instalador final Offline con Inno Setup 6 (ISCC.exe)...")
    iscc = _find_iscc()
    iss_file = ROOT / "installer" / "videostudio.iss"
    subprocess.run([str(iscc), "/Q", f"/DMyAppVersion={version}", str(iss_file)], cwd=str(ROOT / "installer"), check=True)

    out_exe = ROOT / "Output" / f"VideoStudio-Setup-v{version}.exe"
    if not out_exe.exists():
        raise FileNotFoundError(f"No se encontró el instalador esperado en {out_exe}")

    sha = _sha256_file(out_exe)
    sha_file = ROOT / "Output" / "SHA256SUMS.txt"
    sha_file.write_text(f"{sha}  {out_exe.name}\n", encoding="utf-8")

    size_mb = round(out_exe.stat().st_size / (1024 * 1024), 2)
    summary = {
        "version": version,
        "installer_exe": str(out_exe),
        "size_mb": size_mb,
        "sha256": sha,
        "sha256_file": str(sha_file),
    }
    print("\n" + "=" * 68)
    print(f"  INSTALADOR CREADO CON EXITO: {out_exe}")
    print(f"  Tamano Offline Todo-en-Uno : {size_mb} MB")
    print(f"  SHA-256                    : {sha}")
    print("=" * 68)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-pyinstaller", action="store_true")
    args = parser.parse_args()
    build_all(skip_pyinstaller=args.skip_pyinstaller)


if __name__ == "__main__":
    main()
