#!/usr/bin/env python3
"""
End-to-End Automated Verification Suite for VideoStudio Pro Windows Installer Edition.

Tests:
  1. Windows DPAPI encryption/decryption & key masking in isolated %APPDATA%.
  2. Free vs. Paid model classification + 3 Smart Profiles + Vision Lock on Stages 4 & 6.
  3. Anthropic <-> OpenAI multimodal Vision & Tool schema translation + Loopback Proxy + Antigravity SDK presence.
  4. GitHub 1-Click Auto-Updater:
       a) Graceful HTTP 404 when Git repo is not created yet ('repo_pending', zero errors).
       b) Live simulated v1.1.0 Release download + PE 'MZ' check + SHA-256 verification + dry-run installer command.
  5. FastAPI endpoints (/api/bootstrap, /api/channels, /api/ai/suggest-niches, Vision Lock HTTP 400, real Edge-TTS MP3 sample).
"""
from __future__ import annotations

import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Isolate all tests from real user %APPDATA%
TEST_APPDATA = Path(tempfile.mkdtemp(prefix="videostudio_test_appdata_"))
os.environ["VIDEOSTUDIO_APPDATA_DIR"] = str(TEST_APPDATA)

from fastapi.testclient import TestClient  # noqa: E402
from src.ai.stage_recommender import build_recommendations, validate_stage_assignment  # noqa: E402
from src.ai.universal_bridge import (  # noqa: E402
    HAS_ANTIGRAVITY_SDK,
    UniversalLoopbackProxy,
    _anthropic_to_openai_response,
    _openai_to_anthropic_payload,
)
from src.backend.api import app  # noqa: E402
from src.backend.secret_store import (  # noqa: E402
    get_public_providers,
    load_providers_with_secrets,
    save_provider_config,
)
from src.updater.github_updater import (  # noqa: E402
    check_for_updates,
    download_update_installer,
    is_newer_version,
    trigger_installer_and_exit,
)


class VideoStudioWindowsTestSuite(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(TEST_APPDATA, ignore_errors=True)

    def test_01_dpapi_secret_store(self) -> None:
        raw_key = "sk-or-v1-super-secret-test-key-998877"
        pub = save_provider_config("openrouter", api_key=raw_key, enabled=True)
        self.assertTrue(pub["has_api_key"])
        self.assertEqual(pub["masked_key"], "sk-or-...8877")

        # Confirm raw key is NOT stored in plaintext on disk!
        disk_file = TEST_APPDATA / "ai_providers.dpapi.json"
        self.assertTrue(disk_file.exists())
        disk_raw = disk_file.read_text(encoding="utf-8")
        self.assertNotIn(raw_key, disk_raw)
        self.assertIn("dpapi:", disk_raw)

        # Confirm round-trip decryption works
        loaded = load_providers_with_secrets()
        self.assertEqual(loaded["openrouter"]["api_key"], raw_key)
        pub_map = get_public_providers()
        self.assertNotIn(raw_key, json.dumps(pub_map))

    def test_02_recommender_free_paid_and_vision_lock(self) -> None:
        sample_models = [
            {
                "key": "openrouter::meta-llama/llama-3.3-70b-instruct:free",
                "provider": "openrouter",
                "provider_label": "OpenRouter",
                "model_id": "meta-llama/llama-3.3-70b-instruct:free",
                "display_name": "Llama 3.3 70B Free",
                "is_free": True,
                "free_note": "100% Gratis ($0)",
                "price_per_1m_in": 0.0,
                "price_per_1m_out": 0.0,
                "supports_vision": False,
                "context_length": 128000,
                "tags": ["GRATIS", "ALTA CALIDAD"],
            },
            {
                "key": "gemini::gemini-2.5-flash",
                "provider": "gemini",
                "provider_label": "Google Gemini",
                "model_id": "gemini-2.5-flash",
                "display_name": "Gemini 2.5 Flash",
                "is_free": True,
                "free_note": "Gratis (AI Studio Free Tier)",
                "price_per_1m_in": 0.0,
                "price_per_1m_out": 0.0,
                "supports_vision": True,
                "context_length": 1000000,
                "tags": ["GRATIS", "VISIÓN", "RÁPIDO"],
            },
            {
                "key": "anthropic::claude-sonnet-4-20250514",
                "provider": "anthropic",
                "provider_label": "Anthropic",
                "model_id": "claude-sonnet-4-20250514",
                "display_name": "Claude Sonnet 4",
                "is_free": False,
                "free_note": "Pago ($3.00/1M)",
                "price_per_1m_in": 3.0,
                "price_per_1m_out": 15.0,
                "supports_vision": True,
                "context_length": 200000,
                "tags": ["PAGO", "VISIÓN", "ALTA CALIDAD"],
            },
        ]

        recs = build_recommendations(sample_models)
        # Free profile must cost $0.00 and assign Vision-capable Gemini Flash to stages 4 & 6
        self.assertEqual(recs["estimated_cost_usd_per_video"]["free"], 0.0)
        self.assertEqual(recs["profiles"]["free"]["visual-asset-reviewer"], "gemini::gemini-2.5-flash")
        self.assertEqual(recs["profiles"]["free"]["video-qa-validator"], "gemini::gemini-2.5-flash")

        # Balanced profile uses free model on mechanical steps and Claude Sonnet 4 on scriptwriting
        self.assertEqual(recs["profiles"]["balanced"]["viral-scriptwriter"], "anthropic::claude-sonnet-4-20250514")
        self.assertIn(
            recs["profiles"]["balanced"]["packaging-archiver"],
            ("gemini::gemini-2.5-flash", "openrouter::meta-llama/llama-3.3-70b-instruct:free"),
        )

        # Vision Lock must reject text-only model on Stage 4 & Stage 6
        ok4, _ = validate_stage_assignment("visual-asset-reviewer", sample_models[0])
        self.assertFalse(ok4)
        ok6, _ = validate_stage_assignment("video-qa-validator", sample_models[0])
        self.assertFalse(ok6)
        ok_vis, _ = validate_stage_assignment("visual-asset-reviewer", sample_models[1])
        self.assertTrue(ok_vis)

    def test_03_antigravity_sdk_and_anthropic_bridge(self) -> None:
        self.assertTrue(HAS_ANTIGRAVITY_SDK, "google-antigravity SDK must be installed")
        proxy_url = UniversalLoopbackProxy.ensure_started()
        self.assertTrue(proxy_url.startswith("http://127.0.0.1:"))

        oai_req = {
            "model": "anthropic::claude-sonnet-4-20250514",
            "messages": [
                {"role": "system", "content": "Eres un auditor visual."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Revisa esta imagen"},
                        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJDRA=="}},
                    ],
                },
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "approve_grid", "description": "Approve", "parameters": {"type": "object"}},
                }
            ],
        }
        anth = _openai_to_anthropic_payload(oai_req)
        self.assertEqual(anth["model"], "claude-sonnet-4-20250514")
        self.assertEqual(anth["system"], "Eres un auditor visual.")
        self.assertEqual(anth["messages"][0]["content"][1]["source"]["data"], "QUJDRA==")
        self.assertEqual(anth["tools"][0]["name"], "approve_grid")

        fake_anth_resp = {
            "id": "msg_123",
            "content": [
                {"type": "text", "text": '{"selected_candidate": 2}'},
            ],
            "usage": {"input_tokens": 120, "output_tokens": 15},
        }
        back_oai = _anthropic_to_openai_response(fake_anth_resp, "anthropic::claude-sonnet-4-20250514")
        self.assertEqual(back_oai["choices"][0]["message"]["content"], '{"selected_candidate": 2}')

    def test_04_github_updater_404_and_1click_upgrade(self) -> None:
        self.assertTrue(is_newer_version("v1.1.0", "1.0.0"))
        self.assertFalse(is_newer_version("v1.0.0", "1.0.0"))

        # Fake PE executable payload ('MZ' header + dummy body)
        fake_exe_bytes = b"MZ" + os.urandom(4096)
        fake_sha = hashlib.sha256(fake_exe_bytes).hexdigest()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        mode = {"return_404": True}

        class _MockGitHubHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_GET(self):
                if self.path == "/releases/latest":
                    if mode["return_404"]:
                        self.send_response(404)
                        self.end_headers()
                        self.wfile.write(b'{"message": "Not Found"}')
                        return
                    rel = {
                        "tag_name": "v1.1.0",
                        "name": "VideoStudio Pro v1.1.0",
                        "body": "Nuevo motor multi-IA",
                        "assets": [
                            {
                                "name": "VideoStudio-Setup-v1.1.0.exe",
                                "size": len(fake_exe_bytes),
                                "browser_download_url": f"http://127.0.0.1:{port}/download/VideoStudio-Setup-v1.1.0.exe",
                            },
                            {
                                "name": "SHA256SUMS.txt",
                                "size": 90,
                                "browser_download_url": f"http://127.0.0.1:{port}/download/SHA256SUMS.txt",
                            },
                        ],
                    }
                    raw = json.dumps(rel).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(raw)
                elif self.path.endswith(".exe"):
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(fake_exe_bytes)))
                    self.end_headers()
                    self.wfile.write(fake_exe_bytes)
                elif self.path.endswith("SHA256SUMS.txt"):
                    txt = f"{fake_sha}  VideoStudio-Setup-v1.1.0.exe\n".encode("utf-8")
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(txt)

        srv = ThreadingHTTPServer(("127.0.0.1", port), _MockGitHubHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        try:
            # 1) Uncreated Git Repo (HTTP 404) -> clean 'repo_pending'
            st_404 = asyncio.run(check_for_updates(custom_api_url=f"http://127.0.0.1:{port}/releases/latest"))
            self.assertEqual(st_404["status"], "repo_pending")
            self.assertFalse(st_404["update_available"])
            self.assertIsNone(st_404["error"])

            # 2) Published v1.1.0 Release -> detects update, downloads, verifies PE MZ + SHA-256!
            mode["return_404"] = False
            st_new = asyncio.run(check_for_updates(custom_api_url=f"http://127.0.0.1:{port}/releases/latest"))
            self.assertEqual(st_new["status"], "update_available")
            self.assertEqual(st_new["latest_version"], "1.1.0")

            dl_dir = TEST_APPDATA / "updates_test"
            dl_res = asyncio.run(download_update_installer(target_dir=dl_dir))
            self.assertTrue(dl_res["ok"])
            self.assertEqual(dl_res["sha256"], fake_sha)
            self.assertTrue(dl_res["state"]["sha256_verified"])

            launch_res = trigger_installer_and_exit(silent=True, dry_run=True)
            self.assertTrue(launch_res["ok"])
            self.assertIn("/RESTARTAPPLICATIONS", launch_res["command"])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_05_fastapi_wizard_and_live_voice_sample(self) -> None:
        with TestClient(app) as client:
            r = client.get("/api/bootstrap")
            self.assertEqual(r.status_code, 200)
            boot = r.json()
            self.assertEqual(boot["version"]["version"], "1.0.5")
            self.assertEqual(len(boot["voices"]), 8)

            # Save channel via Wizard endpoint
            cr = client.post("/api/channels", json={
                "name": "Imperio Oculto",
                "group": "finanzas_poder",
                "language": "es",
                "niche": "Secretos Financieros",
                "purpose": "monetization",
                "voice_preference": "es-MX-JorgeNeural",
                "subtitle_style": "hybrid",
                "subtitle_color": "yellow",
                "platforms": ["youtube_shorts"],
            })
            self.assertEqual(cr.status_code, 200)
            self.assertEqual(cr.json()["channel_id"], "imperio_oculto")

            # Clear active channel (Modo Libre / Sin canal)
            clr = client.post("/api/channels/active/_clear_")
            self.assertEqual(clr.status_code, 200)
            self.assertIsNone(clr.json()["active_default_channel"])

            # Delete channel endpoint
            dr = client.delete("/api/channels/imperio_oculto")
            self.assertEqual(dr.status_code, 200)
            # Delete gallery video endpoint safety check (must reject outside publications)
            bad_del = client.delete('/api/gallery?folder=C:/Windows')
            # Valid gallery video deletion inside publications_dir
            from src.backend.app_paths import get_workspace_dir
            pub_root = get_workspace_dir() / 'videos' / 'publicaciones' / 'test_channel' / '2026-11-06_test_video'
            pub_root.mkdir(parents=True, exist_ok=True)
            (pub_root / 'video_final.mp4').write_bytes(b'dummy video')
            good_del = client.delete(f'/api/gallery?folder={pub_root}')
            self.assertEqual(good_del.status_code, 200)
            self.assertFalse(pub_root.exists())
            self.assertEqual(bad_del.status_code, 400)

            # Cooldown unblock & orphan purge endpoint
            cdel = client.delete("/api/gallery/cooldown?topic=nonexistent_topic")
            self.assertEqual(cdel.status_code, 200)
            self.assertTrue(cdel.json()["ok"])
            cpurge = client.delete("/api/gallery/cooldown?all_orphans=true")
            self.assertEqual(cpurge.status_code, 200)
            self.assertTrue(cpurge.json()["ok"])

            # Niche suggestions endpoint
            nr = client.post("/api/ai/suggest-niches", json={"language": "en", "purpose": "monetization"})
            self.assertEqual(nr.status_code, 200)
            self.assertGreaterEqual(len(nr.json()["suggestions"]), 3)

            # Real Edge-TTS voice sample synthesis
            vr = client.get("/api/voices/sample/es-MX-JorgeNeural")
            self.assertEqual(vr.status_code, 200)
            self.assertGreater(len(vr.content), 4000)

    def test_06_qa_self_healing_sanitizer_and_thumbnail_enhance(self) -> None:
        from PIL import Image, ImageEnhance
        from src.backend.pipeline_runner import _sanitize_and_bound_script

        # 1) Verify PIL.ImageEnhance works cleanly
        img = Image.new("RGB", (320, 180), (40, 80, 160))
        bright = ImageEnhance.Brightness(img).enhance(1.15)
        self.assertEqual(bright.size, (320, 180))

        # 2) Verify QA script sanitizer strips forbidden farewells and bounds oversized scripts to target words
        bloated = " ".join(["El Sol esconde una tormenta geomagnética colosal capaz de apagar satélites."] * 22)
        bloated += " Suscríbete y dale like para más videos."
        healed = _sanitize_and_bound_script(bloated, ideal_words=145, lang="es")
        self.assertNotIn("suscríbete", healed.lower())
        self.assertNotIn("dale like", healed.lower())
        self.assertLessEqual(len(healed.split()), 160)
        self.assertTrue(healed.endswith("?"))

    def test_07_dynamic_live_pipeline_timer(self) -> None:
        from src.backend.pipeline_runner import PipelineJobManager
        import time

        mgr = PipelineJobManager()
        self.assertFalse(mgr.get_state()["active"])

        # Simulate running job with past start timestamp
        mgr._current_job = {
            "active": True,
            "status": "running",
            "started_at": time.time() - 3.5,
            "total_elapsed_sec": 0.0,
            "stages": [
                {"id": "trend-researcher", "name": "Trend Researcher", "status": "running", "started_at": time.time() - 1.8, "elapsed_sec": 0.0}
            ]
        }
        st = mgr.get_state()
        self.assertGreaterEqual(st["total_elapsed_sec"], 3.4)
        self.assertGreaterEqual(st["stages"][0]["elapsed_sec"], 1.7)

        # Complete stage and verify static recorded time
        mgr._set_stage("trend-researcher", status="done", elapsed_sec=2.45)
        st_done = mgr.get_state()
        self.assertEqual(st_done["stages"][0]["status"], "done")
        self.assertEqual(st_done["stages"][0]["elapsed_sec"], 2.45)


if __name__ == "__main__":
    unittest.main(verbosity=2)
