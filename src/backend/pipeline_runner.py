#!/usr/bin/env python3
"""
Async Real-Time 9-Subagent Pipeline Orchestrator for VideoStudio Pro Desktop.

Supports:
  - 100% Unattended Mode ('auto') and Interactive Copilot Mode ('copilot' pause on Script & 2x2 Grid).
  - Macro-parallelism on Stages 3 (viral-copywriter) & 4 (visual-asset-reviewer).
  - Standalone Pixabay/Pexels HD vertical B-Roll downloader (works on any clean PC without external engines).
  - Live progress state + Δt phase timers + visual preview artifacts for the Desktop Studio UI.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any
import uuid

import httpx
from PIL import Image

from src.ai.model_scanner import scan_all_providers
from src.ai.stage_recommender import PIPELINE_STAGES, build_recommendations
from src.ai.universal_bridge import run_stage_agent
from src.backend.app_paths import get_python_script_cmd, get_workspace_dir, load_app_settings
from src.backend.hardware_doctor import purge_video_cache

NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0


class PipelineJobManager:
    def __init__(self) -> None:
        self._current_job: dict[str, Any] | None = None
        self._resume_event = asyncio.Event()
        self._copilot_payload: dict[str, Any] = {}

    def get_state(self) -> dict[str, Any]:
        if not self._current_job:
            return {"active": False, "status": "idle", "stages": []}
        job = dict(self._current_job)
        now = time.time()
        job_status = job.get("status")
        started_at = job.get("started_at")
        if started_at and job_status in ("running", "awaiting_copilot"):
            job["total_elapsed_sec"] = round(now - started_at, 2)

        stages = []
        for s in job.get("stages", []):
            sc = dict(s)
            if sc.get("status") == "running" and sc.get("started_at"):
                sc["elapsed_sec"] = round(now - sc["started_at"], 2)
            stages.append(sc)
        job["stages"] = stages
        return job

    def submit_copilot_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._current_job or self._current_job.get("status") != "awaiting_copilot":
            return {"ok": False, "error": "No hay ninguna aprobación de Copiloto pendiente."}
        self._copilot_payload = payload or {}
        self._resume_event.set()
        return {"ok": True}

    async def start_production(
        self,
        channel_id: str | None = None,
        custom_topic: str | None = None,
        mode: str | None = None,
        demo_mode: bool = False,
    ) -> dict[str, Any]:
        if self._current_job and self._current_job.get("status") in ("running", "awaiting_copilot"):
            return {"ok": False, "error": "Ya hay una producción en curso."}

        settings = load_app_settings()
        prod_mode = mode or settings.get("production_mode", "auto")
        run_id = f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        ws = get_workspace_dir()
        run_dir = ws / "pipeline_runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Resolve active channel
        ch_id, ch_cfg = _resolve_channel(ws, channel_id, demo_mode=demo_mode)

        # Resolve per-stage models
        scan = await scan_all_providers(force_refresh=False)
        recs = build_recommendations(scan.get("models", []), settings.get("stage_models"))
        profile = settings.get("model_profile", "balanced")
        if profile == "custom" and recs["validated_custom"]:
            stage_map = recs["validated_custom"]
        else:
            stage_map = recs["profiles"].get(profile) or recs["profiles"].get("balanced") or {}

        if not stage_map:
            return {
                "ok": False,
                "error": "No hay ningún proveedor de IA conectado con modelos activos. Conecta al menos una IA en 'Modelos IA' o en el Wizard.",
            }

        stages_state = [
            {
                "id": st["id"],
                "step": st["step"],
                "name": st["name"],
                "role": st["role"],
                "requires_vision": st["requires_vision"],
                "model_key": stage_map.get(st["id"], ""),
                "status": "pending",  # pending | running | waiting_user | done | skipped | error
                "elapsed_sec": 0.0,
                "summary": "",
            }
            for st in PIPELINE_STAGES
        ]

        self._current_job = {
            "active": True,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "channel_id": ch_id,
            "channel_name": ch_cfg.get("name", ch_id),
            "language": ch_cfg.get("language", "es"),
            "voice": ch_cfg.get("voice_preference", "es-MX-JorgeNeural"),
            "mode": prod_mode,
            "demo_mode": demo_mode,
            "status": "running",
            "started_at": time.time(),
            "total_elapsed_sec": 0.0,
            "copilot_gate": None,  # "script" | "visuals" | None
            "copilot_data": {},
            "stages": stages_state,
            "previews": {
                "trend_brief": None,
                "script_data": None,
                "viral_metadata": None,
                "candidates_grid": None,
                "mosaico_clips": None,
                "hero_image": None,
                "qa_strip": None,
                "thumbnail": None,
                "final_video": None,
                "publication_folder": None,
            },
            "logs": [f"Iniciando producción para '{ch_cfg.get('name', ch_id)}' ({ch_cfg.get('language', 'es').upper()})..."],
            "error": None,
        }

        asyncio.create_task(self._execute_pipeline(ws, run_dir, ch_id, ch_cfg, custom_topic, prod_mode, demo_mode, stage_map))
        return {"ok": True, "run_id": run_id, "state": self.get_state()}

    def _set_stage(self, stage_id: str, **kwargs: Any) -> None:
        if not self._current_job:
            return
        for s in self._current_job["stages"]:
            if s["id"] == stage_id:
                if kwargs.get("status") == "running" and "started_at" not in kwargs and not s.get("started_at"):
                    kwargs["started_at"] = time.time()
                s.update(kwargs)
                break
        self._current_job["total_elapsed_sec"] = round(time.time() - self._current_job["started_at"], 2)

    def _log(self, msg: str) -> None:
        if not self._current_job:
            return
        stamp = time.strftime("%H:%M:%S")
        self._current_job["logs"].append(f"[{stamp}] {msg}")
        self._current_job["total_elapsed_sec"] = round(time.time() - self._current_job["started_at"], 2)

    async def _wait_copilot(self, gate: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self._current_job:
            return {}
        self._resume_event.clear()
        self._copilot_payload = {}
        self._current_job["status"] = "awaiting_copilot"
        self._current_job["copilot_gate"] = gate
        self._current_job["copilot_data"] = data
        await self._resume_event.wait()
        self._current_job["status"] = "running"
        self._current_job["copilot_gate"] = None
        return dict(self._copilot_payload)

    async def _execute_pipeline(
        self,
        ws: Path,
        run_dir: Path,
        ch_id: str,
        ch_cfg: dict,
        custom_topic: str | None,
        prod_mode: str,
        demo_mode: bool,
        stage_map: dict[str, str],
    ) -> None:
        scripts_dir = ws / "scripts"
        lang = ch_cfg.get("language", "es")
        niche = ch_cfg.get("niche", "Curiosidades y Misterios")
        voice = ch_cfg.get("voice_preference", "es-MX-JorgeNeural" if lang == "es" else "en-US-ChristopherNeural")
        sub_style = ch_cfg.get("subtitle_style", "hormozi")
        sub_color = ch_cfg.get("subtitle_color", "yellow")

        try:
            # =========================================================================
            # STAGE 1: trend-researcher
            # =========================================================================
            t_s1 = time.time()
            self._set_stage("trend-researcher", status="running", summary="Consultando RSS Trends + Cooldown 30 días...")
            trends_file = run_dir / "market_trends.json"
            await _run_cli_script(scripts_dir / "fetch_trends_data.py", "--output", str(trends_file), cwd=ws)
            blocked_topics = _get_recent_group_topics(ws, ch_id)
            trends_snippet = trends_file.read_text(encoding="utf-8")[:2500] if trends_file.exists() else "{}"

            t1_prompt = (
                f"Canal: {ch_cfg.get('name')} | Idioma: {lang} | Nicho: {niche}\n"
                f"Tema pedido por usuario (opcional): {custom_topic or 'ELECCIÓN LIBRE DE ALTO IMPACTO'}\n"
                f"Temas BLOQUEADOS por Cooldown de 30 días en este grupo (PROHIBIDO repetir): {blocked_topics}\n"
                f"Tendencias actuales: {trends_snippet}\n\n"
                "Devuelve EXCLUSIVAMENTE un objeto JSON válido con estas claves exactas:\n"
                '{"selected_topic": "...", "viral_angle": "...", "real_subject_entity": "nombre concreto fotografiable en Wikipedia/Wikimedia (ej. Giant squid, Nikola Tesla, Mariana Trench)", "why_viral": "..."}'
            )
            r1 = await run_stage_agent("trend-researcher", stage_map["trend-researcher"], t1_prompt)
            if not r1["ok"]:
                raise RuntimeError(f"Trend Researcher falló: {r1.get('error')}")
            trend_brief = r1["json"] if isinstance(r1["json"], dict) else {
                "selected_topic": custom_topic or f"El misterio oculto de {niche}",
                "viral_angle": "Dato contraintuitivo verificado",
                "real_subject_entity": custom_topic or niche,
            }
            (run_dir / "trend_brief.json").write_text(json.dumps(trend_brief, indent=2, ensure_ascii=False), encoding="utf-8")
            self._current_job["previews"]["trend_brief"] = trend_brief
            self._set_stage(
                "trend-researcher",
                status="done",
                elapsed_sec=round(time.time() - t_s1, 2),
                summary=f"Tema: {trend_brief.get('selected_topic', '')[:58]}",
            )
            self._log(f"Tema aprobado: {trend_brief.get('selected_topic')}")

            # =========================================================================
            # STAGE 2: viral-scriptwriter (Strict 62-72s word count + zero double goodbye)
            # =========================================================================
            t_s2 = time.time()
            self._set_stage("viral-scriptwriter", status="running", summary="Redactando guión de 5 compases (62-72s)...")
            min_w, max_w = (150, 168) if lang == "es" else (162, 182)
            lang_label = "Español neutro dinámico" if lang == "es" else "Natural high-retention English"
            t2_prompt = (
                f"Redacta el guión viral hablado para un Short de 62 a 72 segundos totales (incluyendo 3.8s de outro visual).\n"
                f"Idioma obligatorio: {lang_label} | Voz: {voice}\n"
                f"Brief de tendencia: {json.dumps(trend_brief, ensure_ascii=False)}\n"
                f"REGLAS ESTRICTAS INNEGOCIABLES:\n"
                f"1. Longitud EXACTA de `full_script`: entre {min_w} y {max_w} palabras habladas fluidas (ni más corto ni más largo, para clavar 62-72s).\n"
                f"2. Estructura de 5 compases continuos sin etiquetas ni acotaciones entre corchetes.\n"
                f"3. CERO DOBLE DESPEDIDA: termina ESTRICTAMENTE con una pregunta abierta/dilema para los comentarios; PROHIBIDO decir 'suscríbete' o 'sígueme'.\n"
                f"4. Incluye `real_subject_query` (entidad real concreta en inglés para buscar su foto real en Wikimedia) y `video_terms_csv` (6 términos visuales en inglés separados por coma para stock vertical).\n\n"
                "Devuelve EXCLUSIVAMENTE este JSON válido:\n"
                '{"topic": "...", "niche": "...", "language": "' + lang + '", "voice_name": "' + voice + '", '
                '"real_subject_query": "...", "video_terms_csv": "term1, term2, term3, term4, term5, term6", "full_script": "..."}'
            )
            r2 = await run_stage_agent("viral-scriptwriter", stage_map["viral-scriptwriter"], t2_prompt)
            if not r2["ok"] or not isinstance(r2["json"], dict) or not r2["json"].get("full_script"):
                raise RuntimeError(f"Viral Scriptwriter falló: {r2.get('error') or 'JSON inválido'}")

            script_data = r2["json"]
            script_data["language"] = lang
            script_data["voice_name"] = voice
            script_data["niche"] = script_data.get("niche") or niche
            script_data["topic"] = script_data.get("topic") or trend_brief.get("selected_topic", niche)

            if prod_mode == "copilot":
                self._set_stage("viral-scriptwriter", status="waiting_user", summary="Esperando tu visto bueno del guión...")
                decision = await self._wait_copilot("script", {"script": script_data})
                if decision.get("full_script"):
                    script_data["full_script"] = decision["full_script"].strip()

            script_path = run_dir / "video_script.json"
            script_path.write_text(json.dumps(script_data, indent=2, ensure_ascii=False), encoding="utf-8")
            self._current_job["previews"]["script_data"] = script_data
            wc = len(script_data["full_script"].split())
            self._set_stage(
                "viral-scriptwriter",
                status="done",
                elapsed_sec=round(time.time() - t_s2, 2),
                summary=f"Guión listo ({wc} palabras · {voice})",
            )

            # =========================================================================
            # MACRO PARALLEL FORK: STAGE 3 (SEO Copy) + STAGE 4 (Real Photo 2x2 + B-Roll)
            # =========================================================================
            async def _branch_seo() -> dict:
                ts = time.time()
                self._set_stage("viral-copywriter", status="running", summary="Extrayendo inteligencia YouTube + Copy CTR...")
                intel_path = run_dir / "viral_intelligence.json"
                await _run_cli_script(
                    scripts_dir / "fetch_viral_intelligence.py",
                    "--topic", script_data["topic"],
                    "--lang", lang,
                    "--output", str(intel_path),
                    cwd=ws,
                )
                intel_txt = intel_path.read_text(encoding="utf-8")[:1800] if intel_path.exists() else "{}"
                p3 = (
                    f"Genera el paquete SEO y textos de miniatura para este guión ({lang.upper()}):\n"
                    f"Guión: {script_data['full_script']}\nInteligencia YouTube: {intel_txt}\n\n"
                    "Devuelve EXCLUSIVAMENTE un JSON válido con:\n"
                    '{"primary_title": "<70 chars ultra clicable", "description": "2 líneas + hashtags", '
                    '"pinned_comment": "pregunta polémica fijada", "tags": ["tag1","tag2","tag3","tag4","tag5"], '
                    '"thumbnail_hook_text": "2 A 4 PALABRAS MAYÚSCULAS", "thumbnail_badge_text": "1 O 2 PALABRAS"}'
                )
                r3 = await run_stage_agent("viral-copywriter", stage_map["viral-copywriter"], p3)
                meta = r3["json"] if (r3["ok"] and isinstance(r3["json"], dict)) else {}
                meta.setdefault("primary_title", script_data["topic"][:68])
                meta.setdefault("description", f"{script_data['topic']} #shorts #viral")
                meta.setdefault("pinned_comment", "¿Qué opinas tú? Te leo abajo 👇" if lang == "es" else "What do you think? Drop your take below 👇")
                meta.setdefault("tags", ["shorts", "viral", niche.lower().split()[0]])
                meta.setdefault("thumbnail_hook_text", "NADIE LO SABÍA" if lang == "es" else "HIDDEN TRUTH")
                meta.setdefault("thumbnail_badge_text", "SECRETO" if lang == "es" else "EXPOSED")
                (run_dir / "viral_metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
                self._current_job["previews"]["viral_metadata"] = meta
                self._set_stage(
                    "viral-copywriter",
                    status="done",
                    elapsed_sec=round(time.time() - ts, 2),
                    summary=f"Título: {meta['primary_title'][:48]}",
                )
                return meta

            async def _branch_visuals() -> dict:
                ts = time.time()
                self._set_stage("visual-asset-reviewer", status="running", summary="Buscando foto real verificada + escenas por frase...")
                subj_query = script_data.get("real_subject_query") or trend_brief.get("real_subject_entity") or script_data["topic"]
                vision_model = stage_map["visual-asset-reviewer"]

                def _progress(msg: str) -> None:
                    self._set_stage("visual-asset-reviewer", status="running", summary=msg[:110])
                    self._log(f"[Visual] {msg}")

                # Precision first: real-photo hunt (multi-retry) and per-beat footage audit run side by side
                photo_res, beats_res = await asyncio.gather(
                    _hunt_verified_real_photo(
                        ws=ws, run_dir=run_dir, scripts_dir=scripts_dir, ch_id=ch_id,
                        subject=subj_query, topic=script_data["topic"], trend_brief=trend_brief,
                        vision_model=vision_model, progress=_progress,
                    ),
                    _collect_beat_clips(
                        ws=ws, run_dir=run_dir, scripts_dir=scripts_dir, script_data=script_data,
                        vision_model=vision_model, progress=_progress,
                    ),
                )

                grid_path = run_dir / "candidates_grid.jpg"
                if grid_path.exists():
                    self._current_job["previews"]["candidates_grid"] = str(grid_path)

                verified = bool(photo_res.get("verified"))
                approved_photos: list[str] = list(photo_res.get("approved_photo_paths") or [])
                selected_idx = photo_res.get("selected_index")

                # Copilot: the user may override the AI verdict with any candidate of the shown grid
                cand_dir = run_dir / "real_candidates"
                cand_files = sorted(cand_dir.glob("candidate_*.*")) if cand_dir.exists() else []
                if prod_mode == "copilot" and cand_files:
                    self._set_stage("visual-asset-reviewer", status="waiting_user", summary="Elige tu foto favorita del Grid 2x2...")
                    dec = await self._wait_copilot("visuals", {
                        "recommended_candidate": selected_idx or 1,
                        "ai_verified": verified,
                        "candidates": [str(p) for p in cand_files[:4]],
                        "grid_path": str(grid_path) if grid_path.exists() else None,
                    })
                    if dec.get("selected_candidate"):
                        pick = max(1, min(len(cand_files), int(dec["selected_candidate"])))
                        approved_photos = [str(cand_files[pick - 1])] + [p for p in approved_photos if p != str(cand_files[pick - 1])]
                        selected_idx, verified = pick, True

                hero_img = run_dir / "hero_image.jpg"
                hero_clip = run_dir / "hero_clip.mp4"
                for stale in (hero_img, hero_clip):
                    if stale.exists():
                        stale.unlink()

                final_clips: list[str] = []
                if verified and approved_photos:
                    with Image.open(approved_photos[0]) as im:
                        im.convert("RGB").save(hero_img, "JPEG", quality=95)
                    self._current_job["previews"]["hero_image"] = str(hero_img)
                    await _run_cli_script(
                        scripts_dir / "convert_image_to_clip.py",
                        "--image-path", str(hero_img),
                        "--output-clip", str(hero_clip),
                        "--duration", "4.0",
                        cwd=ws,
                    )
                    if hero_clip.exists():
                        final_clips.append(str(hero_clip))  # Guaranteed Slot #0 (0-4s Hook)
                    else:
                        verified = False

                # Assemble footage strictly in script order (beat 1 -> beat 5)
                beats = beats_res.get("beats") or []
                if hero_clip.exists() and beats and len(beats[0]["clips"]) > 1:
                    beats[0]["clips"] = beats[0]["clips"][:-1]  # the real photo already covers the first 4 s
                broll_ordered = [c for b in beats for c in b["clips"] if Path(c).exists()]

                if not broll_ordered:
                    self._log("[Visual] Ninguna escena obtuvo clips: usando descarga de respaldo.")
                    fallback = await _download_stock_broll_standalone(ws, run_dir, script_data.get("video_terms_csv", ""), target_count=16)
                    broll_ordered = [str(c) for c in fallback]
                final_clips.extend(broll_ordered)
                if not final_clips:
                    raise RuntimeError("No se pudieron obtener clips visuales. Verifica tu clave de Pixabay/Pexels en Ajustes.")

                # Clean thumbnail source (no subtitles) from the best-ranked clip of the opening scene
                thumb_src = run_dir / "thumbnail_source.jpg"
                if broll_ordered:
                    await _extract_frame(Path(broll_ordered[0]), thumb_src)

                # Preview mosaic of the footage that actually made it into the video
                mosaico_path = run_dir / "mosaico_clips.jpg"
                if broll_ordered:
                    await _run_cli_script(
                        scripts_dir / "generate_contact_sheet.py",
                        "--clips-list", ",".join(broll_ordered),
                        "--output", str(mosaico_path),
                        cwd=ws,
                    )
                    if mosaico_path.exists():
                        self._current_job["previews"]["mosaico_clips"] = str(mosaico_path)

                ai_ok = sum(b.get("approved_by_ai", 0) for b in beats)
                unreviewed = sum(b.get("filled_unreviewed", 0) for b in beats)
                photo_attempts = len(photo_res.get("attempts") or [])
                materials_payload = {
                    "approved_clips": final_clips,
                    "hero_image": str(hero_img) if (verified and hero_img.exists()) else None,
                    "hero_clip": str(hero_clip) if (verified and hero_clip.exists()) else None,
                    "verified_real_photo": bool(verified and hero_img.exists()),
                    "selected_candidate": selected_idx,
                    "approved_photo_paths": approved_photos if verified else [],
                    "photo_attempts": photo_res.get("attempts") or [],
                    "thumbnail_source": str(thumb_src) if thumb_src.exists() else None,
                    "beats": beats,
                }
                mat_path = run_dir / "approved_materials.json"
                mat_path.write_text(json.dumps(materials_payload, indent=2, ensure_ascii=False), encoding="utf-8")

                photo_note = (
                    f"Foto real verificada (intento {photo_attempts})"
                    if materials_payload["verified_real_photo"]
                    else f"Foto real descartada tras {photo_attempts} intentos"
                )
                clips_note = f"{ai_ok} clips aprobados por IA en {len(beats)} escenas"
                if unreviewed:
                    clips_note += f" (+{unreviewed} de reserva)"
                self._set_stage(
                    "visual-asset-reviewer",
                    status="done",
                    elapsed_sec=round(time.time() - ts, 2),
                    summary=f"{photo_note} · {clips_note}",
                )
                return materials_payload

            viral_meta, materials_info = await asyncio.gather(_branch_seo(), _branch_visuals())

            # =========================================================================
            # STAGE 5: video-renderer (Direct FFmpeg + GPU ~20s)
            # =========================================================================
            t_s5 = time.time()
            self._set_stage("video-renderer", status="running", summary="Renderizando en GPU (Orden secuencial + Subtítulos 58%)...")
            video_out = run_dir / "video_final.mp4"
            render_rc, render_out = await _run_cli_script(
                scripts_dir / "run_pipeline_job.py",
                "--mode", "render",
                "--script-json", str(script_path),
                "--materials-json", str(run_dir / "approved_materials.json"),
                "--output-video", str(video_out),
                "--channel", ch_id,
                "--subtitle-style", sub_style,
                "--subtitle-color", sub_color,
                cwd=ws,
            )
            if render_rc != 0 or not video_out.exists():
                raise RuntimeError(f"Error en renderizado GPU: {render_out[-350:]}")

            self._current_job["previews"]["final_video"] = str(video_out)
            self._set_stage(
                "video-renderer",
                status="done",
                elapsed_sec=round(time.time() - t_s5, 2),
                summary=f"Render GPU completado en {round(time.time() - t_s5, 1)}s",
            )

            # =========================================================================
            # STAGE 6: video-qa-validator (FFprobe 62-72s + Multimodal Vision on qa_strip.jpg)
            # =========================================================================
            t_s6 = time.time()
            self._set_stage("video-qa-validator", status="running", summary="Auditando 62-72s y tira panorámica QA...")
            qa_rc, qa_stdout = await _run_cli_script(
                scripts_dir / "run_qa_audit.py",
                "--video-path", str(video_out),
                "--script-json", str(script_path),
                "--output-dir", str(run_dir),
                "--emit-certificate",
                cwd=ws,
            )
            qa_strip = run_dir / "qa_strip.jpg"
            if qa_strip.exists():
                self._current_job["previews"]["qa_strip"] = str(qa_strip)

            qa_cert_file = run_dir / "qa_certificate.json"
            qa_cert = json.loads(qa_cert_file.read_text(encoding="utf-8")) if qa_cert_file.exists() else {"qa_status": "PASS"}

            # Multimodal Vision check on qa_strip.jpg
            if qa_strip.exists():
                p6 = (
                    "Inspecciona esta tira QA de 5 fotogramas del Short renderizado (1080x1920). "
                    "Verifica que no haya fotogramas totalmente negros ni subtítulos cortados fuera de pantalla. "
                    'Devuelve JSON: {"visual_pass": true, "notes": "..."}'
                )
                r6 = await run_stage_agent("video-qa-validator", stage_map["video-qa-validator"], p6, image_paths=[qa_strip])
                if r6["ok"] and isinstance(r6["json"], dict):
                    qa_cert["vision_audit"] = r6["json"]
                    qa_cert_file.write_text(json.dumps(qa_cert, indent=2, ensure_ascii=False), encoding="utf-8")

            dur_s = (qa_cert.get("technical_probe") or {}).get("duration", 65.0)
            if qa_cert.get("qa_status") == "FAIL":
                raise RuntimeError(f"QA bloqueó el video: {qa_cert.get('failures')}")

            self._set_stage(
                "video-qa-validator",
                status="done",
                elapsed_sec=round(time.time() - t_s6, 2),
                summary=f"PASS Certificado ({dur_s}s · 1080x1920)",
            )

            # =========================================================================
            # STAGE 7: thumbnail-designer
            # =========================================================================
            t_s7 = time.time()
            self._set_stage("thumbnail-designer", status="running", summary="Generando miniatura viral con Badge 74px...")
            thumb_out = run_dir / "miniatura_viral.jpg"
            thumb_args = [
                "--video-path", str(video_out),
                "--hook-text", str(viral_meta.get("thumbnail_hook_text", "SECRETO OCULTO")).upper(),
                "--badge-text", str(viral_meta.get("thumbnail_badge_text", "IMPACTANTE")).upper(),
                "--output", str(thumb_out),
            ]
            if (run_dir / "hero_image.jpg").exists():
                thumb_args.extend(["--frame-path", str(run_dir / "hero_image.jpg")])
            await _run_cli_script(scripts_dir / "create_viral_thumbnail.py", *thumb_args, cwd=ws)
            if thumb_out.exists():
                self._current_job["previews"]["thumbnail"] = str(thumb_out)
            self._set_stage(
                "thumbnail-designer",
                status="done",
                elapsed_sec=round(time.time() - t_s7, 2),
                summary="Miniatura lista sobre foto real aprobada",
            )

            # =========================================================================
            # STAGE 8: packaging-archiver (30d History + 1.5 GB LRU Cap)
            # =========================================================================
            t_s8 = time.time()
            self._set_stage("packaging-archiver", status="running", summary="Empaquetando publicación y aplicando LRU 1.5 GB...")
            slug = re.sub(r"[^a-z0-9]+", "-", script_data["topic"].lower()).strip("-")[:42] or "video-viral"
            _, pkg_stdout = await _run_cli_script(
                scripts_dir / "manage_storage_and_archive.py",
                "--run-dir", str(run_dir),
                "--channel", ch_id,
                "--slug", slug,
                "--video-path", str(video_out),
                "--thumbnail-path", str(thumb_out),
                cwd=ws,
            )
            pub_folder = None
            try:
                parsed_pkg = json.loads(pkg_stdout[pkg_stdout.find("{") :])
                pub_folder = (parsed_pkg.get("package_manifest") or {}).get("publication_folder")
                if pub_folder:
                    self._current_job["previews"]["publication_folder"] = pub_folder
                    if Path(pub_folder, "video_final.mp4").exists():
                        self._current_job["previews"]["final_video"] = str(Path(pub_folder, "video_final.mp4"))
            except Exception:
                pass
            self._set_stage(
                "packaging-archiver",
                status="done",
                elapsed_sec=round(time.time() - t_s8, 2),
                summary="Archivado + Cooldown 30d registrado",
            )

            # =========================================================================
            # STAGE 9: social-media-publisher
            # =========================================================================
            platforms = ch_cfg.get("platforms") or []
            if demo_mode or not platforms:
                self._set_stage(
                    "social-media-publisher",
                    status="skipped",
                    elapsed_sec=0.0,
                    summary="Omitido (Modo Local / Sin redes activas)",
                )
            else:
                t_s9 = time.time()
                self._set_stage("social-media-publisher", status="running", summary=f"Verificando sesiones ({', '.join(platforms)})...")
                sess_dir = ws / "config" / "sessions" / ch_id
                has_any_session = sess_dir.exists() and any(sess_dir.glob("*_session.json"))
                if has_any_session and pub_folder and (scripts_dir / "publish_video.py").exists():
                    await _run_cli_script(
                        scripts_dir / "publish_video.py",
                        "--package-dir", str(pub_folder),
                        "--channel", ch_id,
                        cwd=ws,
                    )
                    self._set_stage(
                        "social-media-publisher",
                        status="done",
                        elapsed_sec=round(time.time() - t_s9, 2),
                        summary=f"Distribución ejecutada ({', '.join(platforms)})",
                    )
                else:
                    self._set_stage(
                        "social-media-publisher",
                        status="skipped",
                        elapsed_sec=round(time.time() - t_s9, 2),
                        summary="Listo en carpeta (conecta tu sesión en Canales para auto-subir)",
                    )

            self._current_job["status"] = "completed"
            self._current_job["total_elapsed_sec"] = round(time.time() - self._current_job["started_at"], 2)
            
            # Automatic disk hygiene: enforce 1.5 GB LRU cap without manual button
            try:
                purge_video_cache(1500.0)
            except Exception:
                pass
            self._log(f"¡Producción completada con éxito en {self._current_job['total_elapsed_sec']}s!")
        except Exception as e:
            if self._current_job:
                self._current_job["status"] = "error"
                self._current_job["error"] = str(e)
                for st in self._current_job["stages"]:
                    if st["status"] in ("running", "waiting_user"):
                        st["status"] = "error"
                        st["summary"] = str(e)[:90]
                self._log(f"ERROR: {e}")


def _sanitize_and_bound_script(text: str, ideal_words: int, lang: str = "es") -> str:
    """Strips forbidden farewell phrases and bounds extreme word-count deviations cleanly at sentence boundaries."""
    forbidden = (
        "suscríbete", "suscribete", "síguenos", "siguenos", "dale like",
        "subscribe", "follow us", "hit the bell", "like and subscribe",
    )
    sentences = [s.strip() for s in re.split(r"(?<=[.!?¿¡])\s+", text.strip()) if s.strip()]
    cleaned_sentences = [
        s for s in sentences
        if not any(bad in s.lower() for bad in forbidden)
    ] or sentences

    joined = " ".join(cleaned_sentences).strip()
    words = joined.split()

    # If the model still overshot by >18%, trim cleanly at sentence boundary and keep an open question
    if len(words) > int(ideal_words * 1.18):
        kept: list[str] = []
        acc = 0
        target_body = max(90, ideal_words - 9)
        for s in cleaned_sentences:
            sw = len(s.split())
            if acc + sw > target_body and kept:
                break
            kept.append(s)
            acc += sw
        joined = " ".join(kept).strip()
        if not joined.endswith("?"):
            q = "¿Y tú qué opinas, estamos realmente preparados?" if lang == "es" else "What do you think, are we truly prepared for this?"
            joined = f"{joined} {q}"
    elif not joined.endswith("?"):
        # Ensure Beat 5 ends with an engaging open question if stripped
        if any(bad in text.lower() for bad in forbidden):
            q = "¿Tú qué harías en ese escenario?" if lang == "es" else "What would you do in that scenario?"
            joined = f"{joined} {q}"

    return joined


def _resolve_channel(ws: Path, channel_id: str | None, demo_mode: bool) -> tuple[str, dict]:
    ch_file = ws / "config" / "channels.json"
    if not demo_mode and ch_file.exists():
        try:
            data = json.loads(ch_file.read_text(encoding="utf-8"))
            channels = data.get("channels") or {}
            cid = channel_id or data.get("active_default_channel") or (next(iter(channels.keys())) if channels else None)
            if cid and cid in channels:
                return cid, channels[cid]
        except Exception:
            pass
    return "piloto_demo", {
        "name": "Piloto Demo Local",
        "group": "demo_group",
        "language": "es",
        "niche": "Ciencia, Misterios y Curiosidades",
        "purpose": "demo",
        "voice_preference": "es-MX-JorgeNeural",
        "subtitle_style": "hormozi",
        "subtitle_color": "yellow",
        "platforms": [],
    }


def _get_recent_group_topics(ws: Path, channel_id: str) -> list[str]:
    hist_file = ws / "config" / "history" / "publication_history.json"
    if not hist_file.exists():
        return []
    try:
        items = json.loads(hist_file.read_text(encoding="utf-8"))
        return [str(x.get("topic", "")) for x in items[-25:] if x.get("topic")]
    except Exception:
        return []


async def _run_cli_script(script_path: Path, *args: str, cwd: Path) -> tuple[int, str]:
    cmd = get_python_script_cmd(script_path, *args)

    def _exec() -> tuple[int, str]:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        res = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=NO_WINDOW,
        )
        combined = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
        return res.returncode, combined.strip()

    return await asyncio.to_thread(_exec)


# =============================================================================
# PRECISION VISUAL ENGINE (multi-retry real photo hunt + per-beat stock audit)
# Priority is precision, not speed: every candidate is audited by the vision
# model and rejected material triggers new, more precise searches.
# =============================================================================
PHOTO_MAX_ATTEMPTS = 5
BEAT_MAX_ROUNDS = 3
BEAT_BATCH_MAX = 8
MAX_CLIP_BYTES = 60 * 1024 * 1024
MIN_CLIP_SECONDS = 4.5


def _parse_json_from_output(text: str) -> dict | None:
    """Extracts the first JSON object printed by a CLI script (ignores warnings around it)."""
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[start:])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
        start = text.find("{", start + 1)
    return None


def _to_int_list(values: Any) -> list[int]:
    out: list[int] = []
    for v in values or []:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


async def _vision_json(stage_id: str, model_key: str, prompt: str, images: list[Path], tries: int = 2) -> dict | None:
    """Runs a vision audit and returns its JSON verdict, retrying once if the model fails or answers malformed JSON."""
    for _ in range(max(1, tries)):
        try:
            r = await run_stage_agent(stage_id, model_key, prompt, image_paths=[str(p) for p in images])
        except Exception:
            r = {"ok": False}
        if r.get("ok") and isinstance(r.get("json"), dict):
            return r["json"]
    return None


async def _hunt_verified_real_photo(
    ws: Path,
    run_dir: Path,
    scripts_dir: Path,
    ch_id: str,
    subject: str,
    topic: str,
    trend_brief: dict,
    vision_model: str,
    progress,
) -> dict:
    """
    Up to PHOTO_MAX_ATTEMPTS search+audit rounds to find a REAL photo of the exact subject.
    Never falls back to a rejected photo: if nothing passes, returns verified=False and the
    video/thumbnail use footage instead.
    """
    rejected_file = run_dir / "rejected_photo_urls.json"
    rejected_urls: list[str] = []
    exclude_terms: list[str] = []
    attempts_log: list[dict] = []
    tried: set[tuple[str, str]] = set()

    queue: list[tuple[str, str]] = [(subject, "wikipedia"), (subject, "commons")]
    entity = str(trend_brief.get("real_subject_entity") or "").strip()
    fallback_pool: list[tuple[str, str]] = []
    if entity and entity.lower() != subject.lower():
        fallback_pool.append((entity, "mixed"))
    fallback_pool.append((f"{subject} {topic}"[:110], "mixed"))
    fallback_pool.append((topic[:90], "wikipedia"))

    def _next_query() -> tuple[str, str] | None:
        for pool in (queue, fallback_pool):
            while pool:
                q, src = pool.pop(0)
                key = (q.strip().lower(), src)
                if q.strip() and key not in tried:
                    tried.add(key)
                    return q.strip(), src
        return None

    attempt = 0
    last_grid: Path | None = None
    last_candidates: list[dict] = []
    while attempt < PHOTO_MAX_ATTEMPTS:
        nq = _next_query()
        if not nq:
            break
        query, source = nq
        attempt += 1
        progress(f"Foto real · intento {attempt}/{PHOTO_MAX_ATTEMPTS}: '{query[:48]}' ({source})")
        rejected_file.write_text(json.dumps(rejected_urls, ensure_ascii=False), encoding="utf-8")
        rc, out = await _run_cli_script(
            scripts_dir / "fetch_real_images.py",
            "--query", query,
            "--output-dir", str(run_dir),
            "--channel", ch_id,
            "--grid-only",
            "--source", source,
            "--exclude-terms", ",".join(exclude_terms),
            "--exclude-urls-file", str(rejected_file),
            cwd=ws,
        )
        report = _parse_json_from_output(out)
        grid = run_dir / "candidates_grid.jpg"
        if rc != 0 or not report or not report.get("success") or not grid.exists():
            attempts_log.append({"attempt": attempt, "query": query, "source": source, "result": "sin resultados"})
            continue

        candidates = report.get("candidates") or []
        try_grid = run_dir / f"candidates_grid_try{attempt}.jpg"
        shutil.copy2(grid, try_grid)
        last_grid, last_candidates = try_grid, candidates

        titles = "\n".join(f"#{c['index']}: {c.get('title', '')}" for c in candidates)
        prompt = (
            f"Eres el auditor visual ESTRICTO de un Short. Tema del video: '{topic}'.\n"
            f"Sujeto real exacto que debe aparecer: '{subject}'.\n"
            f"Adjunto la cuadrícula 2x2 de fotos candidatas del intento {attempt} "
            "(#1 arriba-izq, #2 arriba-der, #3 abajo-izq, #4 abajo-der). Títulos de origen:\n"
            f"{titles}\n\n"
            "REGLAS INNEGOCIABLES:\n"
            "- APRUEBA solo fotos que muestren de verdad el sujeto exacto, o un documento/objeto/lugar/persona real "
            "directamente ligado al tema (ej. la hoja original de una señal, el lugar exacto, la persona exacta).\n"
            "- RECHAZA homónimos (plantas, productos, personas o lugares distintos con el mismo nombre), mapas, logos, "
            "gráficos o diagramas, dibujos, fotos borrosas, con texto basura o que no prueban nada del tema.\n"
            "- `selected_candidate` = la mejor aprobada para el gancho (0-4 s) y la portada: nítida y que funcione "
            "recortada en vertical 9:16.\n"
            "- Si NINGUNA sirve: selected_candidate = null. PROHIBIDO elegir 'la menos mala'.\n"
            "- Si rechazas todo, propone 2 consultas nuevas en inglés más precisas para encontrar el sujeto real "
            "(retry_queries) y palabras que delatan los homónimos detectados (exclude_terms).\n\n"
            'Devuelve EXCLUSIVAMENTE JSON: {"selected_candidate": 2, "approved_candidates": [2, 4], '
            '"reason": "...", "retry_queries": ["...", "..."], "exclude_terms": ["..."]}'
        )
        verdict = await _vision_json("visual-asset-reviewer", vision_model, prompt, [try_grid]) or {}
        valid_idx = {int(c["index"]) for c in candidates}
        approved = [i for i in _to_int_list(verdict.get("approved_candidates")) if i in valid_idx]
        selected = None
        try:
            if verdict.get("selected_candidate") is not None:
                selected = int(verdict["selected_candidate"])
        except (TypeError, ValueError):
            selected = None
        if selected not in valid_idx:
            selected = approved[0] if approved else None
        elif selected not in approved:
            approved.insert(0, selected)

        attempts_log.append({
            "attempt": attempt,
            "query": query,
            "source": source,
            "candidates": [c.get("title", "") for c in candidates],
            "selected_candidate": selected,
            "approved_candidates": approved,
            "reason": verdict.get("reason", "sin veredicto de la IA"),
        })

        if selected is not None:
            approved_dir = run_dir / "approved_photos"
            shutil.rmtree(approved_dir, ignore_errors=True)
            approved_dir.mkdir(parents=True, exist_ok=True)
            approved_paths: list[str] = []
            by_idx = {int(c["index"]): c for c in candidates}
            for idx in [selected] + [a for a in approved if a != selected]:
                src_path = Path(by_idx[idx]["path"])
                if src_path.exists():
                    dst = approved_dir / f"photo_{len(approved_paths) + 1:02d}{src_path.suffix.lower()}"
                    shutil.copy2(src_path, dst)
                    approved_paths.append(str(dst))
            shutil.copy2(try_grid, run_dir / "candidates_grid.jpg")
            progress(f"Foto real verificada en el intento {attempt} ('{query[:40]}')")
            return {
                "verified": bool(approved_paths),
                "approved_photo_paths": approved_paths,
                "grid_path": str(run_dir / "candidates_grid.jpg"),
                "candidates": candidates,
                "selected_index": selected,
                "attempts": attempts_log,
            }

        # Rejected round: never show these photos again and refine the next searches
        rejected_urls.extend(c.get("url", "") for c in candidates if c.get("url"))
        for term in verdict.get("exclude_terms") or []:
            t = str(term).strip().lower()
            if t and t not in exclude_terms and t not in subject.lower():
                exclude_terms.append(t)
        for rq in reversed(verdict.get("retry_queries") or []):
            rq = str(rq).strip()
            if rq:
                queue.insert(0, (rq, "mixed"))
                fallback_pool.insert(0, (rq, "commons"))

    if last_grid and last_grid.exists():
        shutil.copy2(last_grid, run_dir / "candidates_grid.jpg")
    progress(f"Ninguna foto real superó la auditoría tras {attempt} intentos: se usará metraje verificado")
    return {
        "verified": False,
        "approved_photo_paths": [],
        "grid_path": str(run_dir / "candidates_grid.jpg") if (run_dir / "candidates_grid.jpg").exists() else None,
        "candidates": last_candidates,
        "selected_index": None,
        "attempts": attempts_log,
    }


def _normalize_visual_beats(script_data: dict) -> list[dict]:
    """Returns 5 ordered beats {beat, narration, search_terms}; rebuilds them evenly from the script if the model omitted them."""
    beats_raw = script_data.get("visual_beats")
    beats: list[dict] = []
    if isinstance(beats_raw, list):
        for i, b in enumerate(beats_raw):
            if not isinstance(b, dict):
                continue
            narration = str(b.get("narration") or "").strip()
            terms = [str(t).strip() for t in (b.get("search_terms") or []) if str(t).strip()]
            if narration and terms:
                beats.append({"beat": len(beats) + 1, "narration": narration, "search_terms": terms[:4]})
    if len(beats) >= 3:
        return beats

    # Fallback: split the script evenly into 5 balanced sentence groups
    sentences = [s.strip() for s in re.split(r"(?<=[.!?¿¡])\s+", script_data.get("full_script", "")) if s.strip()]
    terms_all = [t.strip() for t in str(script_data.get("video_terms_csv", "")).split(",") if t.strip()]
    if not terms_all:
        terms_all = [script_data.get("topic", "cinematic footage")]

    n = 5
    if len(sentences) >= n:
        k, m = divmod(len(sentences), n)
        chunks = [sentences[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]
    else:
        chunks = [[s] for s in sentences]
        while len(chunks) < n:
            chunks.append([script_data.get("topic", "")])

    beats = []
    for i, chunk in enumerate(chunks):
        t1 = terms_all[i % len(terms_all)]
        t2 = terms_all[(i + 1) % len(terms_all)] if len(terms_all) > 1 else t1
        t_chunk = [t1, t2] if t1 != t2 else [t1]
        beats.append({
            "beat": i + 1,
            "narration": " ".join(chunk).strip() or script_data.get("topic", ""),
            "search_terms": t_chunk[:3],
        })
    return beats


def _pick_pixabay_rendition(videos: dict) -> dict | None:
    renditions = [v for v in (videos or {}).values() if isinstance(v, dict) and v.get("url")]
    renditions.sort(key=lambda v: (v.get("width") or 0) * (v.get("height") or 0), reverse=True)
    for v in renditions:
        size = int(v.get("size") or 0)
        if size == 0 or size <= MAX_CLIP_BYTES:
            return v
    return renditions[-1] if renditions else None


async def _search_stock_videos(client: httpx.AsyncClient, term: str, pix_key: str, pex_key: str, cache: dict) -> list[dict]:
    """Searches one visual term on Pexels (portrait) and Pixabay (film first, then all). Results are cached per run."""
    if term in cache:
        return cache[term]

    async def _get(url: str, **kw) -> httpx.Response | None:
        for i in range(2):
            try:
                r = await client.get(url, **kw)
                if r.status_code == 429 and i == 0:
                    await asyncio.sleep(3.0)
                    continue
                return r
            except Exception:
                if i == 0:
                    await asyncio.sleep(1.0)
        return None

    found: list[dict] = []
    if pex_key:
        r = await _get(
            "https://api.pexels.com/videos/search",
            params={"query": term, "orientation": "portrait", "per_page": 12},
            headers={"Authorization": pex_key},
        )
        if r is not None and r.status_code == 200:
            for v in r.json().get("videos", []):
                if float(v.get("duration") or 0) < MIN_CLIP_SECONDS:
                    continue
                files = [f for f in (v.get("video_files") or []) if f.get("link") and (f.get("height") or 0) >= (f.get("width") or 1)]
                files.sort(key=lambda f: abs((f.get("height") or 0) - 1920))
                if files:
                    f = files[0]
                    found.append({"id": f"pex_{v.get('id')}", "url": f["link"], "w": f.get("width") or 0, "h": f.get("height") or 0, "term": term})

    if pix_key:
        hits: list[dict] = []
        for extra in ({"video_type": "film"}, {}):
            r = await _get(
                "https://pixabay.com/api/videos/",
                params={"key": pix_key, "q": term, "per_page": 15, "safesearch": "true", **extra},
            )
            if r is not None and r.status_code == 200:
                hits.extend(r.json().get("hits", []))
            if len(hits) >= 6:
                break
        for hit in hits:
            if float(hit.get("duration") or 0) < MIN_CLIP_SECONDS:
                continue
            rend = _pick_pixabay_rendition(hit.get("videos") or {})
            if not rend:
                continue
            w, h = int(rend.get("width") or 0), int(rend.get("height") or 0)
            if w * h < 1280 * 720:
                continue
            found.append({"id": f"pix_{hit.get('id')}", "url": rend["url"], "w": w, "h": h, "term": term, "tags": hit.get("tags", "")})

    unique: list[dict] = []
    seen: set[str] = set()
    for c in found:
        if c["id"] not in seen:
            seen.add(c["id"])
            unique.append(c)
    cache[term] = unique
    return unique


async def _download_stock_clip(client: httpx.AsyncClient, cand: dict, cache_dir: Path, dest: Path) -> Path | None:
    cache_file = cache_dir / f"{hashlib.md5(cand['id'].encode()).hexdigest()[:14]}.mp4"
    if not cache_file.exists() or cache_file.stat().st_size < 10_000:
        tmp = cache_file.with_suffix(".part")
        for _ in range(2):
            try:
                async with client.stream("GET", cand["url"]) as resp:
                    if resp.status_code != 200:
                        continue
                    with open(tmp, "wb") as fh:
                        async for chunk in resp.aiter_bytes(1 << 20):
                            fh.write(chunk)
                if tmp.exists() and tmp.stat().st_size > 10_000:
                    tmp.replace(cache_file)
                    break
            except Exception:
                await asyncio.sleep(1.0)
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    if cache_file.exists() and cache_file.stat().st_size > 10_000:
        os.utime(cache_file, None)  # LRU freshness
        shutil.copy2(cache_file, dest)
        return dest
    return None


def _interleave_by_term(cands_by_term: list[list[dict]]) -> list[dict]:
    out: list[dict] = []
    i = 0
    while any(i < len(lst) for lst in cands_by_term):
        for lst in cands_by_term:
            if i < len(lst):
                out.append(lst[i])
        i += 1
    return out


async def _collect_beat_clips(
    ws: Path,
    run_dir: Path,
    scripts_dir: Path,
    script_data: dict,
    vision_model: str,
    progress,
) -> dict:
    """
    For each of the 5 narrative beats: search footage for what the narrator literally says,
    audit a contact sheet with the vision model, and retry with AI-proposed terms (up to
    BEAT_MAX_ROUNDS) until enough relevant, cinematic clips are approved. Order follows the script.
    """
    beats = _normalize_visual_beats(script_data)
    broll_dir = run_dir / "broll_clips"
    broll_dir.mkdir(parents=True, exist_ok=True)
    mosaics_dir = run_dir / "beat_mosaics"
    mosaics_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = ws / "storage" / "cache_videos"
    cache_dir.mkdir(parents=True, exist_ok=True)

    creds = {"pixabay_api_keys": [], "pexels_api_keys": []}
    st_file = ws / "config" / "stock_credentials.json"
    if st_file.exists():
        try:
            creds.update(json.loads(st_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    pix_key = str((creds.get("pixabay_api_keys") or [""])[0] or "").strip()
    pex_key = str((creds.get("pexels_api_keys") or [""])[0] or "").strip()

    lang = script_data.get("language", "es")
    words_per_sec = 2.55 if lang == "es" else 2.75
    speech_sec = len(script_data.get("full_script", "").split()) / words_per_sec
    total_slots = max(10, math.ceil(speech_sec / 4.0) + 1)
    total_words = sum(len(b["narration"].split()) for b in beats) or 1

    used_ids: set[str] = set()
    search_cache: dict = {}
    beat_results: list[dict] = []
    sem = asyncio.Semaphore(4)

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=True) as client:
        for b in beats:
            need = min(3, max(2, round(total_slots * len(b["narration"].split()) / total_words)))
            approved: list[tuple[dict, Path]] = []
            leftovers: list[tuple[dict, Path]] = []
            seen_ids: set[str] = set()
            tried_terms: set[str] = set()
            terms = list(b["search_terms"])
            rounds_log: list[dict] = []

            for rnd in range(1, BEAT_MAX_ROUNDS + 1):
                terms_now = [t for t in terms if t.lower() not in tried_terms]
                if not terms_now:
                    terms_now = [f"{t} cinematic" for t in b["search_terms"] if f"{t} cinematic".lower() not in tried_terms][:2]
                if not terms_now:
                    break
                tried_terms.update(t.lower() for t in terms_now)
                progress(f"Escena {b['beat']}/{len(beats)} · ronda {rnd}/{BEAT_MAX_ROUNDS}: {', '.join(terms_now[:3])[:70]}")

                per_term = [await _search_stock_videos(client, t, pix_key, pex_key, search_cache) for t in terms_now]
                fresh = [c for c in _interleave_by_term(per_term) if c["id"] not in seen_ids and c["id"] not in used_ids]
                missing = need - len(approved)
                batch = fresh[:min(BEAT_BATCH_MAX, max(5, missing + 3))]
                seen_ids.update(c["id"] for c in batch)
                if not batch:
                    rounds_log.append({"round": rnd, "terms": terms_now, "result": "sin clips nuevos"})
                    terms = []
                    continue

                async def _dl(i: int, cand: dict) -> tuple[dict, Path] | None:
                    async with sem:
                        dest = broll_dir / f"b{b['beat']}_r{rnd}_{i:02d}_{cand['id']}.mp4"
                        p = await _download_stock_clip(client, cand, cache_dir, dest)
                        return (cand, p) if p else None

                downloaded = [x for x in await asyncio.gather(*[_dl(i, c) for i, c in enumerate(batch, 1)]) if x]
                if not downloaded:
                    rounds_log.append({"round": rnd, "terms": terms_now, "result": "descarga fallida"})
                    continue

                mosaic = mosaics_dir / f"escena{b['beat']}_ronda{rnd}.jpg"
                await _run_cli_script(
                    scripts_dir / "generate_contact_sheet.py",
                    "--clips-list", ",".join(str(p) for _, p in downloaded),
                    "--output", str(mosaic),
                    cwd=ws,
                )
                verdict: dict = {}
                if mosaic.exists():
                    prompt = (
                        f"Eres el auditor visual ESTRICTO de un Short sobre '{script_data.get('topic', '')}'.\n"
                        f"ESCENA {b['beat']} de {len(beats)}. Durante esta escena el narrador dice EXACTAMENTE:\n"
                        f"\"{b['narration']}\"\n\n"
                        f"Necesito {missing} clip(s) de 4 segundos que ilustren LITERALMENTE lo que se dice. "
                        f"La hoja adjunta muestra {len(downloaded)} clips numerados #01 a #{len(downloaded):02d} "
                        f"(un fotograma de cada uno). Términos buscados: {', '.join(terms_now)}.\n\n"
                        "APRUEBA solo metraje real y cinematográfico que muestre el objeto, lugar, acción o fenómeno "
                        "mencionado en la frase, o su equivalente visual directo.\n"
                        "RECHAZA: sujetos sin relación con la frase, épocas/países/especies que contradicen el contexto, "
                        "animaciones 3D baratas o caricaturas, fondos planos, texto o marcas de agua, duplicados casi "
                        "idénticos y tomas genéricas de relleno.\n"
                        "Ordena approved_ranked del MEJOR al peor. Si faltan clips buenos, propone 3 "
                        "alternative_search_terms en inglés (concretos, filmables y distintos a los ya usados).\n\n"
                        'Devuelve EXCLUSIVAMENTE JSON: {"approved_ranked": [3, 1], "rejected": [2, 4], '
                        '"reason": "...", "alternative_search_terms": ["...", "...", "..."]}'
                    )
                    verdict = await _vision_json("visual-asset-reviewer", vision_model, prompt, [mosaic]) or {}

                n_dl = len(downloaded)
                ranked = [n for n in _to_int_list(verdict.get("approved_ranked")) if 1 <= n <= n_dl]
                rejected_nums = set(n for n in _to_int_list(verdict.get("rejected")) if 1 <= n <= n_dl)
                ranked = list(dict.fromkeys(n for n in ranked if n not in rejected_nums))
                for n in ranked:
                    approved.append(downloaded[n - 1])
                for n in range(1, n_dl + 1):
                    if n not in ranked and n not in rejected_nums:
                        leftovers.append(downloaded[n - 1])
                    elif n in rejected_nums:
                        try:
                            downloaded[n - 1][1].unlink()
                        except OSError:
                            pass

                rounds_log.append({
                    "round": rnd,
                    "terms": terms_now,
                    "mosaic": str(mosaic),
                    "approved": [downloaded[n - 1][0]["id"] for n in ranked],
                    "rejected": [downloaded[n - 1][0]["id"] for n in sorted(rejected_nums)],
                    "reason": verdict.get("reason", "sin veredicto de la IA"),
                })
                if len(approved) >= need:
                    break
                terms = [str(t).strip() for t in (verdict.get("alternative_search_terms") or []) if str(t).strip()]

            filled_from_leftovers = 0
            if len(approved) < need and leftovers:
                take = leftovers[:need - len(approved)]
                filled_from_leftovers = len(take)
                approved.extend(take)
            chosen = approved[:need]

            # Beat fulfillment: if chosen has >= 1 on-topic clip, the beat is satisfied;
            # intelligent intra-beat reuse will cut it dynamically across duration with alternating zoom/offsets.
            # Only if the beat has ZERO clips, borrow from leftovers or search remaining topic terms.
            if len(chosen) == 0:
                if leftovers:
                    take = leftovers.pop(0)
                    chosen.append(take)
                    filled_from_leftovers += 1
                else:
                    all_topic_terms = [t.strip() for t in str(script_data.get("video_terms_csv", "")).split(",") if t.strip()]
                    rem_terms = [t for t in all_topic_terms if t.lower() not in tried_terms]
                    if rem_terms:
                        tried_terms.add(rem_terms[0].lower())
                        fb_res = await _search_stock_videos(client, rem_terms[0], pix_key, pex_key, search_cache)
                        fb_fresh = [c for c in fb_res if c["id"] not in seen_ids and c["id"] not in used_ids]
                        if fb_fresh:
                            cand = fb_fresh[0]
                            dest = broll_dir / f"b{b['beat']}_topic_{cand['id']}.mp4"
                            p = await _download_stock_clip(client, cand, cache_dir, dest)
                            if p:
                                chosen.append((cand, p))
                                filled_from_leftovers += 1

            for cand, _ in chosen:
                used_ids.add(cand["id"])
            beat_results.append({
                "beat": b["beat"],
                "narration": b["narration"],
                "needed": need,
                "clips": [str(p) for _, p in chosen],
                "approved_by_ai": len(chosen) - filled_from_leftovers,
                "filled_unreviewed": filled_from_leftovers,
                "rounds": rounds_log,
            })

    return {"beats": beat_results, "total_slots": total_slots}


async def _extract_frame(clip: Path, out_path: Path) -> bool:
    """Extracts a clean frame (no subtitles) at ~40% of a source clip for thumbnails."""
    def _run() -> bool:
        dur = 4.0
        try:
            pr = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(clip)],
                capture_output=True, text=True, creationflags=NO_WINDOW, timeout=20,
            )
            dur = float((pr.stdout or "4").strip() or 4)
        except Exception:
            pass
        ts = max(0.5, min(dur * 0.4, 3.5))
        res = subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{ts:.2f}", "-i", str(clip), "-frames:v", "1", "-q:v", "2", "-update", "1", str(out_path)],
            capture_output=True, creationflags=NO_WINDOW, timeout=40,
        )
        return res.returncode == 0 and out_path.exists()
    return await asyncio.to_thread(_run)


async def _download_stock_broll_standalone(ws: Path, run_dir: Path, terms_csv: str, target_count: int = 16) -> list[Path]:
    """
    Standalone vertical HD stock video downloader (Pexels + Pixabay + Local LRU Cache).
    Zero dependency on external MoneyPrinterTurbo installation!
    """
    broll_dir = run_dir / "broll_clips"
    broll_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = ws / "storage" / "cache_videos"
    cache_dir.mkdir(parents=True, exist_ok=True)

    st_file = ws / "config" / "stock_credentials.json"
    creds = {"pixabay_api_keys": [], "pexels_api_keys": [], "provider_mode": "both"}
    if st_file.exists():
        try:
            creds.update(json.loads(st_file.read_text(encoding="utf-8")))
        except Exception:
            pass

    pix_key = (creds.get("pixabay_api_keys") or [""])[0].strip()
    pex_key = (creds.get("pexels_api_keys") or [""])[0].strip()
    terms = [t.strip() for t in terms_csv.split(",") if t.strip()] or ["cinematic dark background", "technology", "earth space", "ocean deep"]

    video_urls: list[tuple[str, str]] = []
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for term in terms[:6]:
            if pex_key:
                try:
                    r = await client.get(
                        "https://api.pexels.com/videos/search",
                        params={"query": term, "orientation": "portrait", "per_page": 4, "size": "medium"},
                        headers={"Authorization": pex_key},
                    )
                    if r.status_code == 200:
                        for v in r.json().get("videos", []):
                            vfiles = v.get("video_files") or []
                            portrait = [vf for vf in vfiles if (vf.get("height") or 0) >= (vf.get("width") or 1) and vf.get("link")]
                            chosen = portrait[0] if portrait else (vfiles[0] if vfiles else None)
                            if chosen and chosen.get("link"):
                                video_urls.append((f"pex_{v.get('id')}", chosen["link"]))
                except Exception:
                    pass

            if pix_key and len(video_urls) < target_count:
                try:
                    r = await client.get(
                        "https://pixabay.com/api/videos/",
                        params={"key": pix_key, "q": term, "per_page": 5, "safesearch": "true"},
                    )
                    if r.status_code == 200:
                        for hit in r.json().get("hits", []):
                            vids = hit.get("videos") or {}
                            med = vids.get("medium") or vids.get("small") or vids.get("large") or {}
                            if med.get("url"):
                                video_urls.append((f"pix_{hit.get('id')}", med["url"]))
                except Exception:
                    pass

        # Deduplicate URLs preserving order
        seen: set[str] = set()
        unique_items: list[tuple[str, str]] = []
        for vid_id, u in video_urls:
            if vid_id not in seen:
                seen.add(vid_id)
                unique_items.append((vid_id, u))

        downloaded: list[Path] = []
        sem = asyncio.Semaphore(6)

        async def _fetch_clip(idx: int, vid_id: str, url: str) -> Path | None:
            cache_file = cache_dir / f"{hashlib.md5(vid_id.encode()).hexdigest()[:14]}.mp4"
            dest_file = broll_dir / f"clip_{idx:02d}_{vid_id}.mp4"
            async with sem:
                if not cache_file.exists() or cache_file.stat().st_size < 10_000:
                    try:
                        resp = await client.get(url)
                        if resp.status_code == 200 and len(resp.content) > 10_000:
                            cache_file.write_bytes(resp.content)
                    except Exception:
                        return None
                if cache_file.exists() and cache_file.stat().st_size > 10_000:
                    os.utime(cache_file, None)  # Touch mtime for LRU freshness
                    shutil.copy2(cache_file, dest_file)
                    return dest_file
            return None

        results = await asyncio.gather(*[
            _fetch_clip(i + 1, vid_id, u) for i, (vid_id, u) in enumerate(unique_items[:target_count])
        ])
        downloaded = [p for p in results if p is not None]

    # Fallback to any cached clips in storage/cache_videos if offline or no stock API key yet
    if not downloaded:
        cached_existing = sorted(cache_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)[:target_count]
        for idx, cp in enumerate(cached_existing):
            dest_file = broll_dir / f"clip_{idx + 1:02d}_cached.mp4"
            shutil.copy2(cp, dest_file)
            downloaded.append(dest_file)

    return downloaded


PIPELINE_MANAGER = PipelineJobManager()
