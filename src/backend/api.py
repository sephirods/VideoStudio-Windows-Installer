#!/usr/bin/env python3
"""
FastAPI Backend for VideoStudio Pro Windows Desktop.
Serves the modern SPA UI and connects Antigravity Multi-AI, Wizard, Live Studio, Gallery, and 1-Click GitHub Updater.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import webbrowser
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.ai.model_scanner import scan_all_providers
from src.ai.stage_recommender import build_recommendations, validate_stage_assignment
from src.ai.universal_bridge import run_stage_agent
from src.backend.app_paths import (
    bootstrap_workspace,
    detect_legacy_cli_state,
    get_appdata_dir,
    get_python_script_cmd,
    get_resource_root,
    get_version_info,
    get_workspace_dir,
    import_legacy_cli_state,
    load_app_settings,
    save_app_settings,
)
from src.backend.hardware_doctor import (
    detect_gpu_and_ffmpeg,
    get_cache_health,
    get_stock_credentials_status,
    purge_video_cache,
    test_and_save_stock_keys,
)
from src.backend.pipeline_runner import PIPELINE_MANAGER
from src.backend.secret_store import get_public_providers, save_provider_config
from src.backend.voice_preview import list_official_voices, synthesize_voice_sample
from src.updater.github_updater import (
    check_for_updates,
    download_update_installer,
    get_updater_state,
    trigger_installer_and_exit,
)

NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0

app = FastAPI(title="VideoStudio Pro Desktop API", version="1.0.0")

# Track interactive social login tasks
_SOCIAL_JOBS: dict[str, dict[str, Any]] = {}


class ProviderSaveReq(BaseModel):
    provider_id: str
    api_key: str | None = None
    base_url: str | None = None
    enabled: bool | None = None
    label: str | None = None


class StockSaveReq(BaseModel):
    pixabay_key: str = ""
    pexels_key: str = ""
    provider_mode: str = "both"


class SettingsSaveReq(BaseModel):
    wizard_completed: bool | None = None
    github_repo: str | None = None
    production_mode: str | None = None
    model_profile: str | None = None
    stage_models: dict[str, str] | None = None
    auto_check_updates: bool | None = None
    minimize_to_tray: bool | None = None


class ChannelSaveReq(BaseModel):
    channel_id: str | None = None
    name: str
    group: str = ""
    language: str = "es"
    niche: str
    purpose: str = "monetization"
    voice_preference: str = "es-MX-JorgeNeural"
    subtitle_style: str = "hormozi"
    subtitle_color: str = "yellow"
    platforms: list[str] = []
    schedule_mode: str = "on_demand"
    schedule_time: str = "19:00"
    set_default: bool = True


class NicheSuggestReq(BaseModel):
    language: str = "es"
    purpose: str = "monetization"


class SocialConnectReq(BaseModel):
    channel_id: str
    platform: str  # youtube | tiktok | instagram


class PipelineStartReq(BaseModel):
    channel_id: str | None = None
    custom_topic: str | None = None
    mode: str | None = None  # auto | copilot
    demo_mode: bool = False


class CopilotDecisionReq(BaseModel):
    full_script: str | None = None
    selected_candidate: int | None = None


class OpenPathReq(BaseModel):
    target: str


def _load_channels_data() -> dict[str, Any]:
    ch_file = get_workspace_dir() / "config" / "channels.json"
    if ch_file.exists():
        try:
            return json.loads(ch_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"active_default_channel": None, "channels": {}}


def _save_channels_data(data: dict[str, Any]) -> None:
    ch_file = get_workspace_dir() / "config" / "channels.json"
    ch_file.parent.mkdir(parents=True, exist_ok=True)
    ch_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _get_session_status_for_channel(channel_id: str) -> dict[str, bool]:
    sess_dir = get_workspace_dir() / "config" / "sessions" / channel_id
    out = {}
    for p in ("youtube", "tiktok", "instagram"):
        f = sess_dir / f"{p}_session.json"
        out[p] = f.exists() and f.stat().st_size > 25
    return out


@app.on_event("startup")
async def _on_startup() -> None:
    bootstrap_workspace(force_sync=False)
    settings = load_app_settings()
    if settings.get("auto_check_updates", True):
        asyncio.create_task(check_for_updates())


@app.get("/api/bootstrap")
async def api_bootstrap() -> dict[str, Any]:
    ws_info = bootstrap_workspace(force_sync=False)
    ver = get_version_info()
    settings = load_app_settings()
    hw_file = get_workspace_dir() / "config" / "hardware.json"
    if hw_file.exists():
        try:
            hw = json.loads(hw_file.read_text(encoding="utf-8"))
            if "ffmpeg_ok" not in hw:
                hw = await asyncio.to_thread(detect_gpu_and_ffmpeg)
        except Exception:
            hw = await asyncio.to_thread(detect_gpu_and_ffmpeg)
    else:
        hw = await asyncio.to_thread(detect_gpu_and_ffmpeg)

    ch_data = _load_channels_data()
    channels_with_sessions = {}
    for cid, cinfo in (ch_data.get("channels") or {}).items():
        item = dict(cinfo)
        item["id"] = cid
        item["sessions"] = _get_session_status_for_channel(cid)
        channels_with_sessions[cid] = item

    return {
        "version": ver,
        "settings": settings,
        "workspace": ws_info,
        "hardware": hw,
        "stock": get_stock_credentials_status(),
        "providers": get_public_providers(),
        "voices": list_official_voices(),
        "channels": {
            "active_default_channel": ch_data.get("active_default_channel"),
            "items": channels_with_sessions,
        },
        "cache": get_cache_health(),
        "legacy_cli": detect_legacy_cli_state(),
        "updater": get_updater_state(),
    }


@app.post("/api/import-legacy")
async def api_import_legacy() -> dict[str, Any]:
    res = import_legacy_cli_state()
    return res


@app.post("/api/settings")
async def api_save_settings(req: SettingsSaveReq) -> dict[str, Any]:
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if "stage_models" in updates and updates["stage_models"]:
        scan = await scan_all_providers(force_refresh=False)
        by_key = {m["key"]: m for m in scan.get("models", [])}
        for stage_id, mkey in updates["stage_models"].items():
            if mkey in by_key:
                ok, reason = validate_stage_assignment(stage_id, by_key[mkey])
                if not ok:
                    raise HTTPException(status_code=400, detail=reason)
    saved = save_app_settings(updates)
    if "github_repo" in updates:
        asyncio.create_task(check_for_updates())
    return {"ok": True, "settings": saved}


@app.get("/api/hardware/refresh")
async def api_refresh_hardware() -> dict[str, Any]:
    hw = await asyncio.to_thread(detect_gpu_and_ffmpeg)
    return {"ok": True, "hardware": hw, "cache": get_cache_health()}


@app.post("/api/stock/save")
async def api_save_stock(req: StockSaveReq) -> dict[str, Any]:
    return await test_and_save_stock_keys(req.pixabay_key, req.pexels_key, req.provider_mode)


@app.post("/api/storage/purge")
async def api_purge_storage(full: bool = Query(default=False)) -> dict[str, Any]:
    keep = 0.0 if full else 1500.0
    return await asyncio.to_thread(purge_video_cache, keep)


@app.get("/api/ai/providers")
async def api_get_providers() -> dict[str, Any]:
    return {"providers": get_public_providers()}


@app.post("/api/ai/providers")
async def api_save_provider(req: ProviderSaveReq) -> dict[str, Any]:
    pub = save_provider_config(
        provider_id=req.provider_id,
        api_key=req.api_key,
        base_url=req.base_url,
        enabled=req.enabled,
        label=req.label,
    )
    scan = await scan_all_providers(force_refresh=True)
    settings = load_app_settings()
    recs = build_recommendations(scan.get("models", []), settings.get("stage_models"))
    return {"ok": True, "provider": pub, "scan": scan, "recommendations": recs}


@app.get("/api/ai/scan")
async def api_scan_models(force: bool = Query(default=False)) -> dict[str, Any]:
    scan = await scan_all_providers(force_refresh=force)
    settings = load_app_settings()
    recs = build_recommendations(scan.get("models", []), settings.get("stage_models"))
    return {"scan": scan, "recommendations": recs, "active_profile": settings.get("model_profile", "balanced")}


@app.post("/api/ai/suggest-niches")
async def api_suggest_niches(req: NicheSuggestReq) -> dict[str, Any]:
    scan = await scan_all_providers(force_refresh=False)
    models = scan.get("models", [])
    if models:
        recs = build_recommendations(models)
        mkey = recs["profiles"]["free"].get("trend-researcher") or recs["profiles"]["balanced"].get("trend-researcher") or models[0]["key"]
        prompt = (
            f"Sugiere 3 nichos faceless ultra rentables para Shorts/TikTok (>60s) en idioma '{req.language}' con objetivo '{req.purpose}'.\n"
            "Devuelve EXCLUSIVAMENTE un JSON con formato:\n"
            '{"suggestions": [{"name": "...", "group_slug": "...", "niche": "...", "rpm_tier": "Alto RPM ($4-$9)", "voice_id": "es-MX-JorgeNeural", "reason": "..."}]}'
        )
        res = await run_stage_agent("trend-researcher", mkey, prompt)
        if res["ok"] and isinstance(res["json"], dict) and res["json"].get("suggestions"):
            return {"ok": True, "source": "ai", "suggestions": res["json"]["suggestions"]}

    # Instant curated fallback when user clicks before connecting an AI key
    if req.language == "en":
        curated = [
            {
                "name": "Hidden Empire",
                "group_slug": "wealth_and_power",
                "niche": "Billionaire Secrets, Economics & Geopolitics",
                "rpm_tier": "RPM $6 - $12",
                "voice_id": "en-US-ChristopherNeural",
                "reason": "Audiencia adulta en EE.UU. y Reino Unido con anunciantes financieros de alto pago.",
            },
            {
                "name": "Neural Shift",
                "group_slug": "ai_and_future_tech",
                "niche": "AI Breakthroughs, Dark Tech & Future Science",
                "rpm_tier": "RPM $5 - $10",
                "voice_id": "en-US-JennyNeural",
                "reason": "Tendencia tecnológica diaria con fotografías reales de robots, chips y laboratorios.",
            },
            {
                "name": "Unsolved Vault",
                "group_slug": "historical_mysteries",
                "niche": "Declassified Files, Deep Ocean & Space Anomalies",
                "rpm_tier": "Alta Retención",
                "voice_id": "en-GB-RyanNeural",
                "reason": "Supera el 75% de retención en videos de más de un minuto gracias al estilo documental.",
            },
        ]
    else:
        curated = [
            {
                "name": "Mente Oculta",
                "group_slug": "psicologia_y_poder",
                "niche": "Psicología Oscura, Leyes del Dinero y Persuasión",
                "rpm_tier": "Alto RPM",
                "voice_id": "es-MX-JorgeNeural",
                "reason": "Une historias atrapantes con anunciantes de negocios y finanzas personales.",
            },
            {
                "name": "Archivo Prohibido",
                "group_slug": "misterios_reales",
                "niche": "Casos Desclasificados, Ciencia Extrema y Abismo Marino",
                "rpm_tier": "Alta Retención",
                "voice_id": "es-ES-AlvaroNeural",
                "reason": "Impacto inmediato en los primeros 4 segundos con fotografías documentales reales.",
            },
            {
                "name": "Pulso Futuro",
                "group_slug": "tecnologia_ia",
                "niche": "Inteligencia Artificial, Hallazgos Médicos y Futuro",
                "rpm_tier": "Tendencia Diaria",
                "voice_id": "es-MX-DaliaNeural",
                "reason": "Noticias nuevas cada día que mantienen tu canal fresco sin repetir temas.",
            },
        ]
    return {"ok": True, "source": "curated", "suggestions": curated}


@app.get("/api/voices")
async def api_list_voices(lang: str | None = None) -> dict[str, Any]:
    return {"voices": list_official_voices(lang)}


@app.get("/api/voices/sample/{voice_id}")
async def api_voice_sample(voice_id: str) -> FileResponse:
    mp3_path = await synthesize_voice_sample(voice_id)
    return FileResponse(str(mp3_path), media_type="audio/mpeg", filename=f"{voice_id}.mp3")


@app.post("/api/channels")
async def api_save_channel(req: ChannelSaveReq) -> dict[str, Any]:
    data = _load_channels_data()
    channels = data.setdefault("channels", {})
    cid = req.channel_id or re.sub(r"[^a-z0-9_]+", "_", req.name.lower()).strip("_") or "canal_1"
    grp = req.group.strip() or re.sub(r"[^a-z0-9_]+", "_", req.niche.lower()).strip("_")[:28] or cid

    channels[cid] = {
        "name": req.name.strip(),
        "group": grp,
        "language": req.language,
        "niche": req.niche.strip(),
        "purpose": req.purpose,
        "target_duration_seconds": [62, 72],
        "voice_preference": req.voice_preference,
        "subtitle_style": req.subtitle_style,
        "subtitle_color": req.subtitle_color,
        "platforms": req.platforms,
        "visual_assets": {"outro_mode": "local", "canva_user": None},
        "schedule": {
            "mode": req.schedule_mode,
            "time": req.schedule_time,
            "cadence": "DAILY",
            "engine": "windows_task_scheduler",
        },
    }
    if req.set_default or not data.get("active_default_channel"):
        data["active_default_channel"] = cid
    _save_channels_data(data)

    # Register or remove Windows Scheduled Task if requested
    schedule_result = None
    task_name = f"VideoStudio_{cid}"
    if sys.platform.startswith("win"):
        if req.schedule_mode == "automated":
            ws = get_workspace_dir()
            sched_script = ws / "scripts" / "universal_scheduler.py"
            if sched_script.exists():
                cmd = get_python_script_cmd(
                    sched_script,
                    "--channel", cid,
                    "--mode", "automated",
                    "--time", req.schedule_time,
                )
                res = await asyncio.to_thread(
                    subprocess.run, cmd, cwd=str(ws), capture_output=True, text=True, creationflags=NO_WINDOW
                )
                schedule_result = {"ok": res.returncode == 0, "output": res.stdout.strip()}
        else:
            await asyncio.to_thread(
                subprocess.run,
                ["schtasks", "/delete", "/tn", task_name, "/f"],
                capture_output=True,
                creationflags=NO_WINDOW,
            )

    return {"ok": True, "channel_id": cid, "channel": channels[cid], "schedule_result": schedule_result}


@app.post("/api/channels/active/{channel_id}")
async def api_set_active_channel(channel_id: str) -> dict[str, Any]:
    data = _load_channels_data()
    if channel_id in ("_clear_", "none", "demo", "null", "libre", ""):
        data["active_default_channel"] = None
        _save_channels_data(data)
        return {"ok": True, "active_default_channel": None}
    if channel_id not in (data.get("channels") or {}):
        raise HTTPException(status_code=404, detail="Canal no encontrado.")
    data["active_default_channel"] = channel_id
    _save_channels_data(data)
    return {"ok": True, "active_default_channel": channel_id}


@app.delete("/api/channels/{channel_id}")
async def api_delete_channel(channel_id: str) -> dict[str, Any]:
    data = _load_channels_data()
    channels = data.get("channels") or {}
    channels.pop(channel_id, None)
    if data.get("active_default_channel") == channel_id:
        data["active_default_channel"] = next(iter(channels.keys()), None)
    _save_channels_data(data)
    return {"ok": True, "active_default_channel": data.get("active_default_channel")}


@app.post("/api/social/connect")
async def api_connect_social(req: SocialConnectReq) -> dict[str, Any]:
    ws = get_workspace_dir()
    script = ws / "scripts" / "connect_account.py"
    if not script.exists():
        raise HTTPException(status_code=404, detail="Script connect_account.py no disponible.")

    job_key = f"{req.channel_id}::{req.platform}"
    _SOCIAL_JOBS[job_key] = {"status": "waiting_login", "started_at": datetime.now().isoformat()}

    async def _runner() -> None:
        cmd = get_python_script_cmd(script, "--channel", req.channel_id, "--platform", req.platform)
        res = await asyncio.to_thread(
            subprocess.run, cmd, cwd=str(ws), capture_output=True, text=True, creationflags=NO_WINDOW
        )
        sess_ok = _get_session_status_for_channel(req.channel_id).get(req.platform, False)
        _SOCIAL_JOBS[job_key] = {
            "status": "connected" if (res.returncode == 0 and sess_ok) else "cancelled",
            "connected": sess_ok,
        }

    asyncio.create_task(_runner())
    return {"ok": True, "job_key": job_key, "status": "waiting_login"}


@app.get("/api/social/status/{channel_id}")
async def api_social_status(channel_id: str) -> dict[str, Any]:
    sessions = _get_session_status_for_channel(channel_id)
    pending = {
        p: (_SOCIAL_JOBS.get(f"{channel_id}::{p}", {}).get("status") == "waiting_login")
        for p in ("youtube", "tiktok", "instagram")
    }
    return {"channel_id": channel_id, "sessions": sessions, "pending": pending}


@app.post("/api/pipeline/start")
async def api_pipeline_start(req: PipelineStartReq) -> dict[str, Any]:
    return await PIPELINE_MANAGER.start_production(
        channel_id=req.channel_id,
        custom_topic=req.custom_topic,
        mode=req.mode,
        demo_mode=req.demo_mode,
    )


@app.get("/api/pipeline/state")
async def api_pipeline_state() -> dict[str, Any]:
    return PIPELINE_MANAGER.get_state()


@app.post("/api/pipeline/copilot")
async def api_pipeline_copilot(req: CopilotDecisionReq) -> dict[str, Any]:
    return PIPELINE_MANAGER.submit_copilot_decision(req.model_dump(exclude_none=True))


@app.get("/api/gallery")
async def api_gallery() -> dict[str, Any]:
    ws = get_workspace_dir()
    pub_root = ws / "videos" / "publicaciones"
    items: list[dict[str, Any]] = []

    if pub_root.exists():
        for manifest_file in sorted(pub_root.rglob("package_manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            pdir = manifest_file.parent
            try:
                man = json.loads(manifest_file.read_text(encoding="utf-8"))
            except Exception:
                man = {}
            vid = pdir / "video_final.mp4"
            thumb = pdir / "miniatura_viral.jpg"
            copy_f = pdir / "copy_publicacion.txt"
            qa_f = pdir / "qa_certificate.json"
            dur = None
            if qa_f.exists():
                try:
                    qa_json = json.loads(qa_f.read_text(encoding="utf-8"))
                    dur = qa_json.get("measured_duration_seconds") or (qa_json.get("technical_probe") or {}).get("duration")
                except Exception:
                    pass
            items.append({
                "channel": man.get("channel") or pdir.parent.name,
                "slug": man.get("slug") or pdir.name,
                "folder": str(pdir),
                "packaged_at": man.get("packaged_at") or datetime.fromtimestamp(manifest_file.stat().st_mtime).isoformat(),
                "video_path": str(vid) if vid.exists() else None,
                "thumbnail_path": str(thumb) if thumb.exists() else None,
                "copy_text": copy_f.read_text(encoding="utf-8") if copy_f.exists() else "",
                "duration_sec": dur,
            })

    # Load 30-day cooldown items & auto-reconcile orphaned entries whose video folder was deleted
    hist_file = ws / "config" / "history" / "publication_history.json"
    cooldown_items: list[dict[str, Any]] = []
    now = datetime.now()
    if hist_file.exists():
        try:
            raw_hist = json.loads(hist_file.read_text(encoding="utf-8"))
            reconciled_hist: list[dict[str, Any]] = []
            hist_changed = False
            for entry in raw_hist:
                v_path = entry.get("video_path")
                # Auto-reconcile: if entry points to a deleted folder, purge orphan
                if v_path:
                    vp = Path(v_path)
                    v_folder = vp.parent if vp.suffix else vp
                    if not v_folder.exists():
                        hist_changed = True
                        continue
                reconciled_hist.append(entry)

            if hist_changed:
                try:
                    hist_file.write_text(json.dumps(reconciled_hist, indent=2, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
                raw_hist = reconciled_hist

            for entry in reversed(raw_hist):
                ts_str = entry.get("published_at") or entry.get("timestamp") or ""
                days_left = 30
                try:
                    dt = datetime.fromisoformat(ts_str)
                    elapsed_days = (now - dt).days
                    days_left = max(0, 30 - elapsed_days)
                except Exception:
                    pass
                if days_left > 0:
                    cooldown_items.append({
                        "channel": entry.get("channel") or entry.get("channel_id", ""),
                        "group": entry.get("group", ""),
                        "topic": entry.get("topic", ""),
                        "image_dhash": entry.get("image_hash", ""),
                        "days_remaining": days_left,
                    })
        except Exception:
            pass

    return {"videos": items, "cooldown_active": cooldown_items[:40], "cache": get_cache_health()}


@app.delete("/api/gallery/cooldown")
async def api_delete_gallery_cooldown(topic: str = Query(None), all_orphans: bool = Query(False)) -> dict[str, Any]:
    ws = get_workspace_dir()
    hist_file = ws / "config" / "history" / "publication_history.json"
    if not hist_file.exists():
        return {"ok": True, "removed": 0, "remaining": 0}
    try:
        raw_hist = json.loads(hist_file.read_text(encoding="utf-8"))
    except Exception:
        raw_hist = []

    initial_count = len(raw_hist)
    if all_orphans:
        survivors: list[dict[str, Any]] = []
        for entry in raw_hist:
            v_path = entry.get("video_path")
            if v_path:
                vp = Path(v_path)
                v_folder = vp.parent if vp.suffix else vp
                if not v_folder.exists():
                    continue
            survivors.append(entry)
        raw_hist = survivors
    elif topic:
        t_clean = topic.strip().lower()
        raw_hist = [h for h in raw_hist if str(h.get("topic", "")).strip().lower() != t_clean]

    removed = initial_count - len(raw_hist)
    hist_file.write_text(json.dumps(raw_hist, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "removed": removed, "remaining": len(raw_hist)}


@app.delete("/api/gallery")
async def api_delete_gallery_video(folder: str = Query(...)) -> dict[str, Any]:
    ws = get_workspace_dir()
    target = Path(folder).resolve()
    pub_root = (ws / "videos" / "publicaciones").resolve()
    try:
        target.relative_to(pub_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ruta de video inválida o fuera de publicaciones.")

    if not target.exists():
        raise HTTPException(status_code=404, detail="El video ya no existe en disco.")

    topic_to_remove = None
    man_file = target / "package_manifest.json"
    if man_file.exists():
        try:
            m = json.loads(man_file.read_text(encoding="utf-8"))
            topic_to_remove = m.get("topic")
        except Exception:
            pass

    shutil.rmtree(target, ignore_errors=True)

    if topic_to_remove:
        hist_file = ws / "config" / "history" / "publication_history.json"
        if hist_file.exists():
            try:
                hist = json.loads(hist_file.read_text(encoding="utf-8"))
                hist = [h for h in hist if h.get("topic") != topic_to_remove]
                hist_file.write_text(json.dumps(hist, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

    return {"ok": True, "deleted_folder": str(target), "cache": get_cache_health()}


@app.get("/api/media")
async def api_serve_media(path: str = Query(...)) -> FileResponse:
    target = Path(path).resolve()
    allowed_roots = [get_appdata_dir().resolve(), get_workspace_dir().resolve()]
    if not any(str(target).lower().startswith(str(r).lower()) for r in allowed_roots):
        raise HTTPException(status_code=403, detail="Acceso denegado fuera del área de trabajo.")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Archivo multimedia no encontrado.")
    mime, _ = mimetypes.guess_type(str(target))
    return FileResponse(str(target), media_type=mime or "application/octet-stream")


@app.get("/api/updater/status")
async def api_updater_status() -> dict[str, Any]:
    return get_updater_state()


@app.post("/api/updater/check")
async def api_updater_check() -> dict[str, Any]:
    return await check_for_updates()


@app.post("/api/updater/download")
async def api_updater_download() -> dict[str, Any]:
    state = get_updater_state()
    if state.get("status") == "downloading":
        return {"ok": True, "state": state}
    asyncio.create_task(download_update_installer())
    await asyncio.sleep(0.05)
    return {"ok": True, "state": get_updater_state()}


@app.post("/api/updater/install")
async def api_updater_install(dry_run: bool = Query(default=False)) -> dict[str, Any]:
    res = trigger_installer_and_exit(silent=True, dry_run=dry_run)
    if res.get("ok") and not dry_run:
        async def _quit_soon() -> None:
            await asyncio.sleep(0.7)
            os._exit(0)
        asyncio.create_task(_quit_soon())
    return res


@app.post("/api/system/open-url")
async def api_open_url(req: OpenPathReq) -> dict[str, Any]:
    if req.target.startswith(("http://", "https://")):
        webbrowser.open(req.target)
        return {"ok": True}
    raise HTTPException(status_code=400, detail="URL inválida.")


@app.post("/api/system/open-folder")
async def api_open_folder(req: OpenPathReq) -> dict[str, Any]:
    p = Path(req.target).resolve()
    if p.exists():
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", str(p if p.is_dir() else p.parent)])
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Carpeta no encontrada.")


# Mount static UI last so /api/* routes take priority
_UI_DIR = get_resource_root() / "src" / "ui"
if _UI_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")
