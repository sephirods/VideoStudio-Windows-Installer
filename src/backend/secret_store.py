#!/usr/bin/env python3
"""
Windows DPAPI Native Secret Store (CryptProtectData / CryptUnprotectData).

Encrypts AI provider API keys at rest tied to the logged-in Windows user account
in %APPDATA%/VideoStudio/ai_providers.dpapi.json — zero external crypto DLL dependencies.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import sys
from pathlib import Path

from src.backend.app_paths import get_appdata_dir

CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _dpapi_encrypt(raw_bytes: bytes) -> str:
    if not sys.platform.startswith("win"):
        return "b64:" + base64.b64encode(raw_bytes).decode("ascii")

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    in_buf = ctypes.create_string_buffer(raw_bytes, len(raw_bytes))
    in_blob = _DATA_BLOB(len(raw_bytes), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
    out_blob = _DATA_BLOB()

    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "VideoStudioProSecret",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _dpapi_decrypt(token: str) -> bytes:
    if token.startswith("b64:"):
        return base64.b64decode(token[4:])
    if not token.startswith("dpapi:"):
        return token.encode("utf-8")

    raw = base64.b64decode(token[6:])
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    in_buf = ctypes.create_string_buffer(raw, len(raw))
    in_blob = _DATA_BLOB(len(raw), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
    out_blob = _DATA_BLOB()

    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


DEFAULT_PROVIDERS = {
    "openrouter": {
        "label": "OpenRouter",
        "enabled": False,
        "api_key": "",
        "base_url": "https://openrouter.ai/api/v1",
        "supports_free_models": True,
        "notes": "Detecta decenas de modelos GRATIS (:free) y pagos con 1 sola API key.",
    },
    "omnirouter": {
        "label": "OmniRouter",
        "enabled": False,
        "api_key": "",
        "base_url": "http://127.0.0.1:20128/v1",
        "supports_free_models": True,
        "notes": "Conecta tu OmniRouter local o cloud para enrutar cuotas gratis, suscripciones y fallbacks.",
    },
    "gemini": {
        "label": "Google Gemini (Antigravity Nativo)",
        "enabled": False,
        "api_key": "",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "supports_free_models": True,
        "notes": "Motor nativo del SDK de Antigravity. Incluye nivel gratuito en Google AI Studio.",
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "enabled": False,
        "api_key": "",
        "base_url": "https://api.anthropic.com/v1",
        "supports_free_models": False,
        "notes": "Ideal para guiones virales (Claude Sonnet 4 / 3.7) y auditoría visual.",
    },
    "openai": {
        "label": "OpenAI (GPT)",
        "enabled": False,
        "api_key": "",
        "base_url": "https://api.openai.com/v1",
        "supports_free_models": False,
        "notes": "Soporta GPT-4.1, GPT-4.1-mini, GPT-4o y serie o4.",
    },
    "groq": {
        "label": "Groq Cloud",
        "enabled": False,
        "api_key": "",
        "base_url": "https://api.groq.com/openai/v1",
        "supports_free_models": True,
        "notes": "Inferencia ultrarrápida con capa gratuita para desarrolladores.",
    },
    "local": {
        "label": "IA Local (Ollama / LM Studio)",
        "enabled": True,
        "api_key": "local",
        "base_url": "http://127.0.0.1:11434/v1",
        "supports_free_models": True,
        "notes": "100% gratis e ilimitado en tu propia PC sin enviar datos afuera.",
    },
}


def _store_path() -> Path:
    return get_appdata_dir() / "ai_providers.dpapi.json"


def mask_secret(key: str) -> str:
    if not key or key == "local":
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:6]}...{key[-4:]}"


def load_providers_with_secrets() -> dict[str, dict]:
    providers = {k: dict(v) for k, v in DEFAULT_PROVIDERS.items()}
    path = _store_path()
    if not path.exists():
        return providers

    try:
        disk_data = json.loads(path.read_text(encoding="utf-8"))
        for pid, entry in disk_data.items():
            base = dict(providers.get(pid, {
                "label": entry.get("label", pid),
                "enabled": False,
                "api_key": "",
                "base_url": entry.get("base_url", ""),
                "supports_free_models": True,
                "notes": "",
            }))
            base["enabled"] = bool(entry.get("enabled", False))
            if entry.get("base_url"):
                base["base_url"] = entry["base_url"].rstrip("/")
            enc_key = entry.get("api_key_enc", "")
            if enc_key:
                try:
                    base["api_key"] = _dpapi_decrypt(enc_key).decode("utf-8")
                except Exception:
                    base["api_key"] = ""
            providers[pid] = base
    except Exception:
        pass
    return providers


def save_provider_config(provider_id: str, api_key: str | None = None, base_url: str | None = None, enabled: bool | None = None, label: str | None = None) -> dict:
    all_p = load_providers_with_secrets()
    cur = dict(all_p.get(provider_id, {
        "label": label or provider_id.title(),
        "enabled": True,
        "api_key": "",
        "base_url": "",
        "supports_free_models": True,
        "notes": "Proveedor OpenAI-compatible personalizado.",
    }))
    if api_key is not None and not api_key.startswith("KEEP_EXISTING"):
        cur["api_key"] = api_key.strip()
    if base_url is not None and base_url.strip():
        cur["base_url"] = base_url.strip().rstrip("/")
    if enabled is not None:
        cur["enabled"] = bool(enabled)
    elif api_key and api_key.strip():
        cur["enabled"] = True
    if label:
        cur["label"] = label

    all_p[provider_id] = cur
    _persist_all(all_p)
    return get_public_providers()[provider_id]


def _persist_all(all_p: dict[str, dict]) -> None:
    out = {}
    for pid, info in all_p.items():
        raw_key = info.get("api_key", "")
        out[pid] = {
            "label": info.get("label", pid),
            "enabled": bool(info.get("enabled", False)),
            "base_url": info.get("base_url", ""),
            "supports_free_models": bool(info.get("supports_free_models", True)),
            "notes": info.get("notes", ""),
            "api_key_enc": _dpapi_encrypt(raw_key.encode("utf-8")) if raw_key else "",
        }
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


def get_public_providers() -> dict[str, dict]:
    """Safe view for Frontend UI (never sends plaintext API keys)."""
    raw = load_providers_with_secrets()
    pub = {}
    for pid, info in raw.items():
        key = info.get("api_key", "")
        has_key = bool(key) and (pid == "local" or len(key) >= 4)
        pub[pid] = {
            "id": pid,
            "label": info.get("label", pid),
            "enabled": bool(info.get("enabled", False)),
            "base_url": info.get("base_url", ""),
            "has_api_key": has_key,
            "masked_key": mask_secret(key),
            "supports_free_models": bool(info.get("supports_free_models", True)),
            "notes": info.get("notes", ""),
        }
    return pub
