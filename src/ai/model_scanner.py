#!/usr/bin/env python3
"""
Live Multi-Provider AI Model Scanner (Free vs. Paid + Vision & Tool Capability Detector).

Supports:
  - OpenRouter (live pricing.prompt == '0' free model detection + architecture.input_modalities)
  - OmniRouter (local or cloud router: detects free/OAuth/combo pools vs paid models)
  - Google Gemini (AI Studio Free Tier detection + native multimodal support)
  - Anthropic (Claude 4 / 3.7 / 3.5 active account models + vision)
  - OpenAI (GPT-4.1 / GPT-4o / o-series active models + vision)
  - Groq Cloud (Developer free-tier ultra-fast models)
  - Local AI (Ollama :11434 / LM Studio :1234 — 100% Free Offline/Local)
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from src.backend.secret_store import load_providers_with_secrets

VISION_KEYWORDS = (
    "vision",
    "-vl",
    "vl-",
    "pixtral",
    "gemini-1.5",
    "gemini-2.0",
    "gemini-2.5",
    "gemini-3",
    "gemini-pro-vision",
    "gemma-3",
    "gpt-4o",
    "gpt-4.1",
    "gpt-4.5",
    "gpt-5",
    "o4-mini",
    "o3",
    "claude-3",
    "claude-sonnet-4",
    "claude-opus-4",
    "claude-haiku-4",
    "llama-3.2-11b",
    "llama-3.2-90b",
    "llama-4",
    "qwen2.5-vl",
    "qwen2-vl",
    "qvq",
    "internvl",
    "llava",
    "minicpm-v",
    "mistral-small-3.1",
    "mistral-medium-3",
)

REASONING_KEYWORDS = (
    "pro",
    "sonnet",
    "opus",
    "gpt-4.1",
    "gpt-4o",
    "gpt-5",
    "o3",
    "o4",
    "deepseek-r1",
    "deepseek-chat",
    "qwen3",
    "qwq",
    "llama-3.3-70b",
    "llama-4",
)

FAST_KEYWORDS = (
    "flash",
    "mini",
    "nano",
    "haiku",
    "lite",
    "8b",
    "7b",
    "instant",
    "turbo",
)

# Known reference pricing ($ per 1M input tokens) when a provider's /models endpoint omits pricing
KNOWN_INPUT_PRICING_PER_1M: dict[str, float] = {
    "gpt-4.1": 2.00,
    "gpt-4.1-mini": 0.40,
    "gpt-4.1-nano": 0.10,
    "gpt-4o": 2.50,
    "gpt-4o-mini": 0.15,
    "o4-mini": 1.10,
    "o3": 2.00,
    "claude-opus-4": 15.00,
    "claude-sonnet-4": 3.00,
    "claude-3-7-sonnet": 3.00,
    "claude-3-5-sonnet": 3.00,
    "claude-3-5-haiku": 0.80,
}

GEMINI_FREE_ELIGIBLE_PREFIXES = (
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemma-3",
)

OMNIROUTER_FREE_HINTS = (
    ":free",
    "/free",
    "-free",
    "free-",
    "gemini-cli",
    "antigravity",
    "iflow",
    "qwen-oauth",
    "kiro",
    "copilot",
    "ollama",
)

_SCAN_CACHE: dict[str, Any] = {"timestamp": 0.0, "data": None}


def _infer_vision(model_id: str, extra_modalities: list[str] | None = None) -> bool:
    if extra_modalities and any("image" in str(m).lower() for m in extra_modalities):
        return True
    low = model_id.lower()
    if "embed" in low or "whisper" in low or "tts" in low or "moderation" in low or "dall-e" in low:
        return False
    return any(k in low for k in VISION_KEYWORDS)


def _infer_tier_tags(model_id: str, is_free: bool, supports_vision: bool) -> list[str]:
    low = model_id.lower()
    tags = ["GRATIS" if is_free else "PAGO"]
    if supports_vision:
        tags.append("VISIÓN")
    if any(k in low for k in REASONING_KEYWORDS):
        tags.append("ALTA CALIDAD")
    if any(k in low for k in FAST_KEYWORDS):
        tags.append("RÁPIDO")
    return tags


def _estimate_known_price(model_id: str) -> float:
    low = model_id.lower()
    for prefix, price in KNOWN_INPUT_PRICING_PER_1M.items():
        if prefix in low:
            return price
    return 1.00


def _is_chat_candidate(model_id: str) -> bool:
    low = model_id.lower()
    excluded = (
        "embedding",
        "text-embedding",
        "tts-",
        "whisper",
        "dall-e",
        "gpt-image",
        "omni-moderation",
        "text-moderation",
        "babbage",
        "davinci",
        "realtime",
        "transcribe",
        "audio-preview",
        "search-preview",
        "aqa",
        "imagen-",
        "veo-",
    )
    return not any(x in low for x in excluded)


async def _scan_openrouter(cfg: dict, client: httpx.AsyncClient) -> dict:
    key = cfg.get("api_key", "").strip()
    base = cfg.get("base_url", "https://openrouter.ai/api/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = await client.get(f"{base}/models", headers=headers)
    r.raise_for_status()
    items = r.json().get("data", [])

    # Also verify key validity if provided
    key_valid = False
    if key:
        kr = await client.get("https://openrouter.ai/api/v1/auth/key", headers=headers)
        key_valid = kr.status_code == 200

    models = []
    for m in items:
        mid = m.get("id", "")
        if not mid or not _is_chat_candidate(mid):
            continue
        pricing = m.get("pricing") or {}
        try:
            p_in = float(pricing.get("prompt", "0") or 0) * 1_000_000
            p_out = float(pricing.get("completion", "0") or 0) * 1_000_000
        except (ValueError, TypeError):
            p_in, p_out = 0.0, 0.0

        is_free = (p_in == 0.0 and p_out == 0.0) or mid.endswith(":free")
        arch = m.get("architecture") or {}
        in_mods = arch.get("input_modalities") or ([arch.get("modality")] if arch.get("modality") else [])
        vis = _infer_vision(mid, in_mods)
        ctx = int(m.get("context_length") or 32768)
        models.append({
            "key": f"openrouter::{mid}",
            "provider": "openrouter",
            "provider_label": "OpenRouter",
            "model_id": mid,
            "display_name": m.get("name") or mid,
            "is_free": is_free,
            "free_note": "100% Gratis ($0)" if is_free else f"${p_in:.2f}/1M",
            "price_per_1m_in": round(p_in, 4),
            "price_per_1m_out": round(p_out, 4),
            "supports_vision": vis,
            "context_length": ctx,
            "tags": _infer_tier_tags(mid, is_free, vis),
        })
    return {"connected": bool(key_valid or not key), "key_verified": key_valid, "models": models}


async def _scan_omnirouter(cfg: dict, client: httpx.AsyncClient) -> dict:
    key = cfg.get("api_key", "").strip()
    base = cfg.get("base_url", "http://127.0.0.1:20128/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = await client.get(f"{base}/models", headers=headers)
    r.raise_for_status()
    payload = r.json()
    items = payload.get("data", payload.get("models", []))

    models = []
    for m in items:
        mid = m.get("id") or m.get("name") or ""
        if not mid or not _is_chat_candidate(mid):
            continue
        pricing = m.get("pricing") or {}
        has_zero_price = False
        p_in = 0.0
        if pricing:
            try:
                p_in = float(pricing.get("prompt", pricing.get("input", 0)) or 0)
                has_zero_price = p_in == 0.0
            except Exception:
                pass
        owned = str(m.get("owned_by", "")).lower()
        tier = str(m.get("tier", m.get("plan", ""))).lower()
        low_all = f"{mid.lower()} {owned} {tier}"
        is_free = has_zero_price or tier == "free" or any(h in low_all for h in OMNIROUTER_FREE_HINTS)
        if not pricing and not is_free:
            p_in = _estimate_known_price(mid)
        vis = _infer_vision(mid, m.get("input_modalities"))
        models.append({
            "key": f"omnirouter::{mid}",
            "provider": "omnirouter",
            "provider_label": "OmniRouter",
            "model_id": mid,
            "display_name": m.get("name") or mid,
            "is_free": is_free,
            "free_note": "Gratis / Cuota Incluida" if is_free else f"Pago (~${p_in:.2f}/1M)",
            "price_per_1m_in": 0.0 if is_free else round(p_in, 4),
            "price_per_1m_out": 0.0 if is_free else round(p_in * 3, 4),
            "supports_vision": vis,
            "context_length": int(m.get("context_length") or 128000),
            "tags": _infer_tier_tags(mid, is_free, vis),
        })
    return {"connected": True, "key_verified": True, "models": models}


async def _scan_gemini(cfg: dict, client: httpx.AsyncClient) -> dict:
    key = cfg.get("api_key", "").strip()
    if not key:
        return {"connected": False, "key_verified": False, "models": []}
    base = cfg.get("base_url", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    r = await client.get(f"{base}/models", params={"key": key})
    r.raise_for_status()
    items = r.json().get("models", [])

    models = []
    for m in items:
        methods = m.get("supportedGenerationMethods") or []
        if "generateContent" not in methods:
            continue
        raw_name = m.get("name", "")
        mid = raw_name.replace("models/", "")
        if not _is_chat_candidate(mid):
            continue
        is_free = any(mid.lower().startswith(pref) for pref in GEMINI_FREE_ELIGIBLE_PREFIXES)
        p_in = 0.0 if is_free else (1.25 if "pro" in mid.lower() else 0.15)
        vis = _infer_vision(mid, ["image"] if "gemini" in mid.lower() or "gemma-3" in mid.lower() else [])
        models.append({
            "key": f"gemini::{mid}",
            "provider": "gemini",
            "provider_label": "Google Gemini",
            "model_id": mid,
            "display_name": m.get("displayName") or mid,
            "is_free": is_free,
            "free_note": "Gratis (AI Studio Free Tier)" if is_free else f"Pago (~${p_in:.2f}/1M)",
            "price_per_1m_in": p_in,
            "price_per_1m_out": 0.0 if is_free else round(p_in * 4, 2),
            "supports_vision": vis,
            "context_length": int(m.get("inputTokenLimit") or 1000000),
            "tags": _infer_tier_tags(mid, is_free, vis),
        })
    return {"connected": True, "key_verified": True, "models": models}


async def _scan_anthropic(cfg: dict, client: httpx.AsyncClient) -> dict:
    key = cfg.get("api_key", "").strip()
    if not key:
        return {"connected": False, "key_verified": False, "models": []}
    base = cfg.get("base_url", "https://api.anthropic.com/v1").rstrip("/")
    r = await client.get(
        f"{base}/models",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    r.raise_for_status()
    items = r.json().get("data", [])

    models = []
    for m in items:
        mid = m.get("id", "")
        if not mid:
            continue
        p_in = _estimate_known_price(mid)
        vis = _infer_vision(mid, ["image"])
        models.append({
            "key": f"anthropic::{mid}",
            "provider": "anthropic",
            "provider_label": "Anthropic",
            "model_id": mid,
            "display_name": m.get("display_name") or mid,
            "is_free": False,
            "free_note": f"Pago (${p_in:.2f}/1M)",
            "price_per_1m_in": p_in,
            "price_per_1m_out": round(p_in * 5, 2),
            "supports_vision": vis,
            "context_length": 200000,
            "tags": _infer_tier_tags(mid, False, vis),
        })
    return {"connected": True, "key_verified": True, "models": models}


async def _scan_openai_compatible(pid: str, label: str, cfg: dict, client: httpx.AsyncClient, default_free: bool = False) -> dict:
    key = cfg.get("api_key", "").strip()
    if pid != "local" and not key:
        return {"connected": False, "key_verified": False, "models": []}
    base = cfg.get("base_url", "").rstrip("/")
    headers = {"Authorization": f"Bearer {key}"} if key and key != "local" else {}
    r = await client.get(f"{base}/models", headers=headers)
    r.raise_for_status()
    payload = r.json()
    items = payload.get("data", payload.get("models", []))

    models = []
    for m in items:
        mid = m.get("id") or m.get("name") or ""
        if not mid or not _is_chat_candidate(mid):
            continue
        is_free = default_free or pid in ("local", "groq")
        p_in = 0.0 if is_free else _estimate_known_price(mid)
        vis = _infer_vision(mid)
        note = "100% Gratis Local" if pid == "local" else ("Gratis (Dev Tier)" if is_free else f"Pago (~${p_in:.2f}/1M)")
        models.append({
            "key": f"{pid}::{mid}",
            "provider": pid,
            "provider_label": label,
            "model_id": mid,
            "display_name": mid,
            "is_free": is_free,
            "free_note": note,
            "price_per_1m_in": p_in,
            "price_per_1m_out": 0.0 if is_free else round(p_in * 4, 2),
            "supports_vision": vis,
            "context_length": int(m.get("context_window") or 128000),
            "tags": _infer_tier_tags(mid, is_free, vis),
        })
    return {"connected": True, "key_verified": True, "models": models}


async def scan_all_providers(force_refresh: bool = False) -> dict:
    """Scans all configured providers in parallel (<2s) and classifies Free vs. Paid models."""
    now = time.time()
    if not force_refresh and _SCAN_CACHE["data"] and (now - _SCAN_CACHE["timestamp"] < 45):
        return _SCAN_CACHE["data"]

    providers = load_providers_with_secrets()
    provider_status: dict[str, dict] = {}
    all_models: list[dict] = []

    async with httpx.AsyncClient(timeout=7.0, follow_redirects=True) as client:
        async def _probe(pid: str, cfg: dict):
            has_creds = pid == "local" or pid == "omnirouter" or bool(cfg.get("api_key", "").strip())
            if not cfg.get("enabled") and not (pid != "local" and bool(cfg.get("api_key", "").strip())):
                provider_status[pid] = {
                    "id": pid,
                    "label": cfg.get("label", pid),
                    "connected": False,
                    "error": None,
                    "free_count": 0,
                    "paid_count": 0,
                }
                return

            if not has_creds:
                provider_status[pid] = {
                    "id": pid,
                    "label": cfg.get("label", pid),
                    "connected": False,
                    "error": "Falta API Key",
                    "free_count": 0,
                    "paid_count": 0,
                }
                return

            try:
                if pid == "openrouter":
                    res = await _scan_openrouter(cfg, client)
                elif pid == "omnirouter":
                    res = await _scan_omnirouter(cfg, client)
                elif pid == "gemini":
                    res = await _scan_gemini(cfg, client)
                elif pid == "anthropic":
                    res = await _scan_anthropic(cfg, client)
                elif pid == "groq":
                    res = await _scan_openai_compatible("groq", "Groq Cloud", cfg, client, default_free=True)
                elif pid == "local":
                    res = await _scan_openai_compatible("local", "IA Local (Ollama/LM Studio)", cfg, client, default_free=True)
                else:
                    res = await _scan_openai_compatible(pid, cfg.get("label", pid), cfg, client, default_free=False)

                m_list = res.get("models", [])
                free_c = sum(1 for x in m_list if x["is_free"])
                paid_c = len(m_list) - free_c
                provider_status[pid] = {
                    "id": pid,
                    "label": cfg.get("label", pid),
                    "connected": res.get("connected", False),
                    "key_verified": res.get("key_verified", False),
                    "error": None,
                    "free_count": free_c,
                    "paid_count": paid_c,
                    "total_count": len(m_list),
                }
                if res.get("connected"):
                    all_models.extend(m_list)
            except Exception as e:
                # Quietly report offline local servers (e.g. Ollama not running) without alarming errors
                err_txt = "Servidor local apagado" if pid in ("local", "omnirouter") else str(e)[:120]
                provider_status[pid] = {
                    "id": pid,
                    "label": cfg.get("label", pid),
                    "connected": False,
                    "error": err_txt,
                    "free_count": 0,
                    "paid_count": 0,
                }

        await asyncio.gather(*[_probe(pid, cfg) for pid, cfg in providers.items()])

    # Sort: Free Vision -> Free Quality -> Paid Quality -> Alphabetical
    all_models.sort(
        key=lambda m: (
            0 if m["is_free"] else 1,
            0 if m["supports_vision"] else 1,
            0 if "ALTA CALIDAD" in m["tags"] else 1,
            m["display_name"].lower(),
        )
    )

    summary = {
        "scanned_at": int(now),
        "total_models": len(all_models),
        "free_models_count": sum(1 for m in all_models if m["is_free"]),
        "paid_models_count": sum(1 for m in all_models if not m["is_free"]),
        "vision_models_count": sum(1 for m in all_models if m["supports_vision"]),
        "free_vision_count": sum(1 for m in all_models if m["is_free"] and m["supports_vision"]),
        "providers": provider_status,
        "models": all_models,
    }
    _SCAN_CACHE["timestamp"] = now
    _SCAN_CACHE["data"] = summary
    return summary
