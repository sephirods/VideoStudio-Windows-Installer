#!/usr/bin/env python3
"""
Universal Antigravity SDK + Multi-Provider Loopback Router Bridge.

1. Uses official `google.antigravity` (v0.1.23):
   - `LocalAgentConfig` for native Google Gemini models.
   - `LocalOpenAIAgentConfig` pointed at a local-only (127.0.0.1) Universal Loopback Proxy
     for OpenRouter, OmniRouter, Anthropic (Claude), OpenAI (GPT), Groq, and Local (Ollama/LM Studio).
2. Translates OpenAI `/v1/chat/completions` <-> Anthropic `/v1/messages` transparently
   (including base64 Vision images and tool schemas).
3. Loads specialist rules directly from `.agents/agents/<stage_id>/agent.md`.
"""
from __future__ import annotations

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import socket
import threading
import time
from typing import Any
import uuid

import httpx

try:
    import google.antigravity as agy
    HAS_ANTIGRAVITY_SDK = True
except Exception:
    agy = None
    HAS_ANTIGRAVITY_SDK = False

from src.backend.app_paths import get_workspace_dir
from src.backend.secret_store import load_providers_with_secrets


def parse_model_key(model_key: str) -> tuple[str, str]:
    if "::" in model_key:
        p, mid = model_key.split("::", 1)
        return p.strip(), mid.strip()
    return "openrouter", model_key.strip()


def _encode_image_data_url(img_path: str | Path) -> tuple[str, str, str]:
    p = Path(img_path)
    mime, _ = mimetypes.guess_type(str(p))
    if not mime:
        mime = "image/jpeg"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return mime, b64, f"data:{mime};base64,{b64}"


def _openai_to_anthropic_payload(body: dict) -> dict:
    """Translates an OpenAI Chat Completions payload into Anthropic /v1/messages format."""
    _, raw_model = parse_model_key(body.get("model", ""))
    messages = body.get("messages", [])
    system_parts: list[str] = []
    anth_messages: list[dict] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            if isinstance(content, str):
                system_parts.append(content)
            elif isinstance(content, list):
                system_parts.extend(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
            continue

        anth_role = "assistant" if role == "assistant" else "user"
        if isinstance(content, str):
            anth_content: Any = content
        elif isinstance(content, list):
            blocks = []
            for part in content:
                ptype = part.get("type")
                if ptype == "text":
                    blocks.append({"type": "text", "text": part.get("text", "")})
                elif ptype == "image_url":
                    url = (part.get("image_url") or {}).get("url", "")
                    if url.startswith("data:") and ";base64," in url:
                        header, b64_data = url.split(";base64,", 1)
                        media_type = header.replace("data:", "") or "image/jpeg"
                        blocks.append({
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": b64_data},
                        })
            anth_content = blocks or ""
        else:
            anth_content = str(content)

        # Handle assistant tool_calls
        if role == "assistant" and msg.get("tool_calls"):
            blocks = [{"type": "text", "text": content}] if isinstance(content, str) and content else []
            for tc in msg["tool_calls"]:
                fn = tc.get("function") or {}
                try:
                    inp = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    inp = {}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id") or f"toolu_{uuid.uuid4().hex[:12]}",
                    "name": fn.get("name", "tool"),
                    "input": inp,
                })
            anth_content = blocks
        elif role == "tool":
            anth_role = "user"
            anth_content = [{
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id", ""),
                "content": str(content),
            }]

        anth_messages.append({"role": anth_role, "content": anth_content})

    out: dict[str, Any] = {
        "model": raw_model,
        "max_tokens": int(body.get("max_tokens") or 4096),
        "messages": anth_messages or [{"role": "user", "content": "Hello"}],
    }
    if system_parts:
        out["system"] = "\n\n".join(s for s in system_parts if s)
    if body.get("temperature") is not None:
        out["temperature"] = float(body["temperature"])

    if body.get("tools"):
        anth_tools = []
        for t in body["tools"]:
            fn = t.get("function") or {}
            if fn.get("name"):
                anth_tools.append({
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
                })
        if anth_tools:
            out["tools"] = anth_tools
    return out


def _anthropic_to_openai_response(anth_resp: dict, requested_model: str) -> dict:
    """Translates Anthropic /v1/messages response into OpenAI chat.completion JSON."""
    text_parts: list[str] = []
    tool_calls: list[dict] = []

    for block in anth_resp.get("content", []):
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_calls.append({
                "id": block.get("id", f"call_{uuid.uuid4().hex[:10]}"),
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                },
            })

    msg: dict[str, Any] = {
        "role": "assistant",
        "content": "\n".join(text_parts) if text_parts else (None if tool_calls else ""),
    }
    if tool_calls:
        msg["tool_calls"] = tool_calls

    usage = anth_resp.get("usage") or {}
    in_tok = int(usage.get("input_tokens") or 0)
    out_tok = int(usage.get("output_tokens") or 0)
    finish = "tool_calls" if tool_calls else "stop"

    return {
        "id": anth_resp.get("id", f"chatcmpl-{uuid.uuid4().hex[:12]}"),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": requested_model,
        "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": in_tok,
            "completion_tokens": out_tok,
            "total_tokens": in_tok + out_tok,
        },
    }


def forward_chat_completion_sync(body: dict) -> tuple[int, dict]:
    """Routes an OpenAI-formatted chat completion request to any configured provider."""
    requested_model = body.get("model", "")
    provider_id, raw_model = parse_model_key(requested_model)
    providers = load_providers_with_secrets()
    cfg = providers.get(provider_id)
    if not cfg:
        return 400, {"error": {"message": f"Proveedor IA no configurado: {provider_id}"}}

    api_key = cfg.get("api_key", "").strip()
    base_url = cfg.get("base_url", "").rstrip("/")
    if provider_id not in ("local", "omnirouter") and not api_key:
        return 401, {"error": {"message": f"Falta API Key para el proveedor '{provider_id}'."}}

    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        if provider_id == "anthropic":
            anth_payload = _openai_to_anthropic_payload(body)
            r = client.post(
                f"{base_url}/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=anth_payload,
            )
            if r.status_code >= 400:
                return r.status_code, {"error": {"message": r.text}}
            return 200, _anthropic_to_openai_response(r.json(), requested_model)

        if provider_id == "gemini":
            # OpenAI-compatible Gemini endpoint on Google AI Studio
            oai_gemini_url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
            fwd = dict(body)
            fwd["model"] = raw_model
            fwd.pop("stream", None)
            r = client.post(
                oai_gemini_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=fwd,
            )
            return r.status_code, (r.json() if r.content else {})

        # OpenRouter, OmniRouter, OpenAI, Groq, Local (Ollama / LM Studio)
        fwd = dict(body)
        fwd["model"] = raw_model
        fwd["stream"] = False
        headers = {"Content-Type": "application/json"}
        if api_key and api_key != "local":
            headers["Authorization"] = f"Bearer {api_key}"
        if provider_id == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/sephirods/VideoStudio-Windows-Installer"
            headers["X-Title"] = "VideoStudio Pro Windows"

        r = client.post(f"{base_url}/chat/completions", headers=headers, json=fwd)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"error": {"message": r.text[:500]}}


class _LoopbackProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return  # Keep console silent

    def do_GET(self) -> None:
        if self.path.endswith("/models"):
            payload = json.dumps({"object": "list", "data": []}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if "/chat/completions" not in self.path:
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
            status, resp_dict = forward_chat_completion_sync(body)
        except Exception as e:
            status, resp_dict = 500, {"error": {"message": str(e)}}

        out_bytes = json.dumps(resp_dict, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out_bytes)))
        self.end_headers()
        self.wfile.write(out_bytes)


class UniversalLoopbackProxy:
    """Singleton 127.0.0.1 OpenAI-compatible bridge for google.antigravity.LocalOpenAIAgentConfig."""

    _lock = threading.Lock()
    _server: ThreadingHTTPServer | None = None
    _port: int = 0

    @classmethod
    def ensure_started(cls) -> str:
        with cls._lock:
            if cls._server is not None:
                return f"http://127.0.0.1:{cls._port}/v1"

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            _, port = sock.getsockname()
            sock.close()

            server = ThreadingHTTPServer(("127.0.0.1", port), _LoopbackProxyHandler)
            t = threading.Thread(target=server.serve_forever, name="AntigravityLoopbackProxy", daemon=True)
            t.start()
            cls._server = server
            cls._port = port
            return f"http://127.0.0.1:{cls._port}/v1"


def load_subagent_instructions(stage_id: str) -> str:
    ws = get_workspace_dir()
    rule_file = ws / ".agents" / "agents" / stage_id / "agent.md"
    if rule_file.exists():
        return rule_file.read_text(encoding="utf-8")
    return f"You are specialist subagent '{stage_id}' of VideoStudio Pro."


def extract_json_object(text: str) -> dict | list | None:
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    candidate = fenced.group(1).strip() if fenced else text.strip()
    try:
        return json.loads(candidate)
    except Exception:
        pass
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except Exception:
            pass
    return None


async def run_stage_agent(
    stage_id: str,
    model_key: str,
    user_prompt: str,
    image_paths: list[str | Path] | None = None,
    use_sdk_harness: bool = False,
) -> dict:
    """
    Executes a specialist AI turn using:
      - `google.antigravity.Agent` (`LocalAgentConfig` / `LocalOpenAIAgentConfig` via Loopback Proxy)
        when `use_sdk_harness=True` and SDK is available, OR
      - Direct low-latency multi-provider completion via the exact same Universal Bridge
        (with automatic fallback so production runs never stall).
    """
    t0 = time.time()
    system_prompt = load_subagent_instructions(stage_id)
    provider_id, raw_model = parse_model_key(model_key)
    providers = load_providers_with_secrets()
    cfg = providers.get(provider_id, {})
    ws = get_workspace_dir()

    if use_sdk_harness and HAS_ANTIGRAVITY_SDK:
        try:
            skills_dir = ws / ".agents" / "skills"
            skills_list = [str(skills_dir)] if skills_dir.exists() else None
            caps = agy.CapabilitiesConfig(
                enable_subagents=False,
                disabled_tools=[agy.BuiltinTools.RUN_COMMAND],
            )
            if provider_id == "gemini" and cfg.get("api_key"):
                agent_cfg = agy.LocalAgentConfig(
                    api_key=cfg["api_key"],
                    model=raw_model,
                    system_instructions=system_prompt,
                    workspaces=[str(ws)],
                    skills_paths=skills_list,
                    capabilities=caps,
                )
            else:
                proxy_url = UniversalLoopbackProxy.ensure_started()
                agent_cfg = agy.LocalOpenAIAgentConfig(
                    model=model_key,
                    base_url=proxy_url,
                    system_instructions=system_prompt,
                    workspaces=[str(ws)],
                    skills_paths=skills_list,
                    capabilities=caps,
                )

            prompt_items: list[Any] = [user_prompt]
            for ip in image_paths or []:
                if Path(ip).exists():
                    prompt_items.append(agy.from_file(Path(ip)))

            async with agy.Agent(agent_cfg) as agent:
                resp = await agent.chat(prompt_items if len(prompt_items) > 1 else user_prompt)
                if resp.text is None:
                    await resp.resolve()
                txt = resp.text or ""
                return {
                    "ok": True,
                    "engine": "google-antigravity-sdk",
                    "model_key": model_key,
                    "elapsed_sec": round(time.time() - t0, 2),
                    "text": txt,
                    "json": extract_json_object(txt),
                }
        except Exception:
            # Seamless fallback to direct Universal Bridge below
            pass

    # Build OpenAI-compatible multimodal message and execute via Universal Bridge
    user_content: Any
    valid_imgs = [Path(p) for p in (image_paths or []) if Path(p).exists()]
    if valid_imgs:
        parts: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        for p in valid_imgs:
            _, _, data_url = _encode_image_data_url(p)
            parts.append({"type": "image_url", "image_url": {"url": data_url}})
        user_content = parts
    else:
        user_content = user_prompt

    body = {
        "model": model_key,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.6,
        "max_tokens": 3500,
    }

    import asyncio
    status, resp = await asyncio.to_thread(forward_chat_completion_sync, body)
    if status >= 400:
        err_msg = (resp.get("error") or {}).get("message") if isinstance(resp, dict) else str(resp)
        return {
            "ok": False,
            "engine": "universal-bridge",
            "model_key": model_key,
            "elapsed_sec": round(time.time() - t0, 2),
            "error": err_msg or f"HTTP {status}",
            "text": "",
            "json": None,
        }

    choices = resp.get("choices") or []
    txt = ((choices[0].get("message") or {}).get("content") or "") if choices else ""
    return {
        "ok": True,
        "engine": "antigravity-universal-bridge",
        "model_key": model_key,
        "elapsed_sec": round(time.time() - t0, 2),
        "text": txt,
        "json": extract_json_object(txt),
    }
