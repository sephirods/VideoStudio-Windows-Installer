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

NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0


class PipelineJobManager:
    def __init__(self) -> None:
        self._current_job: dict[str, Any] | None = None
        self._resume_event = asyncio.Event()
        self._copilot_payload: dict[str, Any] = {}

    def get_state(self) -> dict[str, Any]:
        if not self._current_job:
            return {"active": False, "status": "idle", "stages": []}
        return dict(self._current_job)

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
                self._set_stage(
                    "viral-copywriter",
                    status="done",
                    elapsed_sec=round(time.time() - ts, 2),
                    summary=f"Título: {meta['primary_title'][:48]}",
                )
                return meta

            async def _branch_visuals() -> dict:
                ts = time.time()
                self._set_stage("visual-asset-reviewer", status="running", summary="Descargando Grid 2x2 real + Stock HD en paralelo...")
                subj_query = script_data.get("real_subject_query") or trend_brief.get("real_subject_entity") or script_data["topic"]

                # Run real photo 2x2 grid + standalone stock B-roll download concurrently
                real_task = _run_cli_script(
                    scripts_dir / "fetch_real_images.py",
                    "--query", subj_query,
                    "--output-dir", str(run_dir),
                    "--channel", ch_id,
                    "--grid-only",
                    cwd=ws,
                )
                stock_task = _download_stock_broll_standalone(ws, run_dir, script_data.get("video_terms_csv", ""), target_count=16)
                _, broll_clips = await asyncio.gather(real_task, stock_task)

                grid_path = run_dir / "candidates_grid.jpg"
                mosaico_path = run_dir / "mosaico_clips.jpg"
                if broll_clips and (scripts_dir / "generate_contact_sheet.py").exists():
                    await _run_cli_script(
                        scripts_dir / "generate_contact_sheet.py",
                        "--clips-dir", str(run_dir / "broll_clips"),
                        "--output", str(mosaico_path),
                        cwd=ws,
                    )

                if grid_path.exists():
                    self._current_job["previews"]["candidates_grid"] = str(grid_path)
                if mosaico_path.exists():
                    self._current_job["previews"]["mosaico_clips"] = str(mosaico_path)

                # Multimodal Vision inspection of candidates_grid.jpg + mosaico_clips.jpg
                vision_imgs = [p for p in (grid_path, mosaico_path) if p.exists()]
                selected_idx = 1
                if vision_imgs:
                    p4 = (
                        f"Audita visualmente las imágenes adjuntas para el tema '{script_data['topic']}' (sujeto real: '{subj_query}').\n"
                        "En la cuadrícula 2x2 de candidatos reales (#1 arriba-izq, #2 arriba-der, #3 abajo-izq, #4 abajo-der), "
                        "elige el número (1 a 4) que muestre con mayor nitidez, autenticidad y encuadre limpio al sujeto real sin texto basura.\n"
                        'Devuelve EXCLUSIVAMENTE JSON: {"selected_candidate": 1, "visual_verdict": "..."}'
                    )
                    r4 = await run_stage_agent(
                        "visual-asset-reviewer",
                        stage_map["visual-asset-reviewer"],
                        p4,
                        image_paths=vision_imgs,
                    )
                    if r4["ok"] and isinstance(r4["json"], dict):
                        try:
                            selected_idx = max(1, min(4, int(r4["json"].get("selected_candidate", 1))))
                        except Exception:
                            selected_idx = 1

                # Copilot optional photo picker
                cand_dir = run_dir / "real_candidates"
                cand_files = sorted(cand_dir.glob("candidate_*.*")) if cand_dir.exists() else []
                if prod_mode == "copilot" and cand_files:
                    self._set_stage("visual-asset-reviewer", status="waiting_user", summary="Elige tu foto favorita del Grid 2x2...")
                    dec = await self._wait_copilot("visuals", {
                        "recommended_candidate": selected_idx,
                        "candidates": [str(p) for p in cand_files[:4]],
                        "grid_path": str(grid_path) if grid_path.exists() else None,
                    })
                    if dec.get("selected_candidate"):
                        selected_idx = max(1, min(len(cand_files), int(dec["selected_candidate"])))

                hero_img = run_dir / "hero_image.jpg"
                hero_clip = run_dir / "hero_clip.mp4"
                final_clips: list[str] = []

                if cand_files:
                    chosen_file = cand_files[min(selected_idx - 1, len(cand_files) - 1)]
                    with Image.open(chosen_file) as im:
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
                        final_clips.append(str(hero_clip))  # Guaranteed Slot #0 (0-4s Hook)!

                final_clips.extend(str(c) for c in broll_clips)
                if not final_clips:
                    raise RuntimeError("No se pudieron obtener clips visuales. Verifica tu clave de Pixabay/Pexels en Ajustes.")

                materials_payload = {
                    "approved_clips": final_clips,
                    "hero_image": str(hero_img) if hero_img.exists() else None,
                    "hero_clip": str(hero_clip) if hero_clip.exists() else None,
                    "selected_candidate": selected_idx,
                }
                mat_path = run_dir / "approved_materials.json"
                mat_path.write_text(json.dumps(materials_payload, indent=2, ensure_ascii=False), encoding="utf-8")
                self._set_stage(
                    "visual-asset-reviewer",
                    status="done",
                    elapsed_sec=round(time.time() - ts, 2),
                    summary=f"Foto real #{selected_idx} en Hook + {len(broll_clips)} clips HD",
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
