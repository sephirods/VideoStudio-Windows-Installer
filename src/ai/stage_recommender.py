#!/usr/bin/env python3
"""
Smart Per-Stage Model Recommender & Vision-Lock Validator for the 9 Subagents.

Generates 3 one-click profiles ('free', 'balanced', 'pro') from the user's connected models
and enforces multimodal Vision capability on stages 4 (visual-asset-reviewer) and 6 (video-qa-validator).
"""
from __future__ import annotations

PIPELINE_STAGES = [
    {
        "id": "trend-researcher",
        "step": 1,
        "name": "1. Trend Researcher",
        "role": "Investigador de Tendencias y Cooldown 30d",
        "requires_vision": False,
        "ideal_profile": "fast",
        "approx_tokens": 2200,
        "reason_hint": "Síntesis rápida de RSS + Google Trends; rinde excelente con modelos rápidos o gratis.",
    },
    {
        "id": "viral-scriptwriter",
        "step": 2,
        "name": "2. Viral Scriptwriter",
        "role": "Guionista de Retención (5 Compases · 62-72s)",
        "requires_vision": False,
        "ideal_profile": "creative",
        "approx_tokens": 3500,
        "reason_hint": "Corazón de la retención viral: aquí brilla un modelo con gran redacción y ritmo narrativo.",
    },
    {
        "id": "viral-copywriter",
        "step": 3,
        "name": "3. Viral Copywriter",
        "role": "Especialista SEO, Título <70c y Debate",
        "requires_vision": False,
        "ideal_profile": "creative",
        "approx_tokens": 2400,
        "reason_hint": "Genera ángulos de alto CTR combinando YouTube Autocomplete y psicología de clic.",
    },
    {
        "id": "visual-asset-reviewer",
        "step": 4,
        "name": "4. Visual Asset Reviewer",
        "role": "Auditor de Fotos Reales (Grid 2x2) y Stock",
        "requires_vision": True,
        "ideal_profile": "vision",
        "approx_tokens": 3800,
        "reason_hint": "OBLIGATORIO VISIÓN: inspecciona candidates_grid.jpg y mosaico_clips.jpg para evitar animales/objetos falsos.",
    },
    {
        "id": "video-renderer",
        "step": 5,
        "name": "5. Video Renderer (GPU)",
        "role": "Coordinador FFmpeg NVENC + Subtítulos 58%",
        "requires_vision": False,
        "ideal_profile": "fast",
        "approx_tokens": 1400,
        "reason_hint": "Orquesta el render GPU determinista (~21s); un modelo ligero/gratis es óptimo.",
    },
    {
        "id": "video-qa-validator",
        "step": 6,
        "name": "6. Video QA Validator",
        "role": "Inspector de Tira QA (5 Fotogramas + 62-72s)",
        "requires_vision": True,
        "ideal_profile": "vision",
        "approx_tokens": 3200,
        "reason_hint": "OBLIGATORIO VISIÓN: audita qa_strip.jpg comprobando márgenes móviles, subtítulos y cero pantallas negras.",
    },
    {
        "id": "thumbnail-designer",
        "step": 7,
        "name": "7. Thumbnail Designer",
        "role": "Diseñador de Miniatura + Badge 74px",
        "requires_vision": False,
        "ideal_profile": "fast",
        "approx_tokens": 1500,
        "reason_hint": "Selecciona el texto de impacto corto (2-4 palabras) sobre hero_image.jpg deduplicada.",
    },
    {
        "id": "packaging-archiver",
        "step": 8,
        "name": "8. Packaging Archiver",
        "role": "Empaquetador + Historial 30d + Caché 1.5 GB",
        "requires_vision": False,
        "ideal_profile": "fast",
        "approx_tokens": 1000,
        "reason_hint": "Tarea estructural de archivo y control dHash; costo cero recomendado.",
    },
    {
        "id": "social-media-publisher",
        "step": 9,
        "name": "9. Social Publisher",
        "role": "Distribuidor Multi-Red con Sesiones Aisladas",
        "requires_vision": False,
        "ideal_profile": "fast",
        "approx_tokens": 1100,
        "reason_hint": "Verifica cookies aisladas y despacha publicación; ideal para modelo rápido/gratis.",
    },
]

CREATIVE_RANK = (
    "claude-sonnet-4",
    "claude-3-7-sonnet",
    "gemini-2.5-pro",
    "gpt-4.1",
    "gpt-4o",
    "claude-3-5-sonnet",
    "deepseek-chat",
    "deepseek-r1",
    "gemini-2.5-flash",
    "qwen3",
    "llama-3.3-70b",
)

VISION_RANK = (
    "gemini-2.5-flash",
    "gpt-4.1-mini",
    "gpt-4o",
    "claude-sonnet-4",
    "gemini-2.5-pro",
    "qwen2.5-vl-72b",
    "qwen2.5-vl-32b",
    "llama-4",
    "gemma-3-27b",
    "gemini-2.0-flash",
    "gpt-4o-mini",
)

FAST_RANK = (
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gpt-4.1-nano",
    "gpt-4.1-mini",
    "gpt-4o-mini",
    "claude-3-5-haiku",
    "llama-3.3-70b",
    "llama-3.1-8b",
    "gemma-3",
)


def _score_model(m: dict, rank_tuple: tuple[str, ...], prefer_free: bool, strict_free: bool) -> int:
    if strict_free and not m["is_free"]:
        return -9999
    score = 0
    if prefer_free and m["is_free"]:
        score += 500
    elif not prefer_free and not m["is_free"]:
        score += 120

    low = m["model_id"].lower()
    for idx, token in enumerate(rank_tuple):
        if token in low:
            score += (len(rank_tuple) - idx) * 35
            break

    if m["provider"] == "gemini":
        score += 20  # Native Antigravity SDK zero-overhead bonus
    return score


def _pick_best(
    models: list[dict],
    requires_vision: bool,
    ideal_profile: str,
    prefer_free: bool,
    strict_free: bool,
) -> dict | None:
    pool = [m for m in models if (not requires_vision or m["supports_vision"])]
    if strict_free:
        free_pool = [m for m in pool if m["is_free"]]
        if free_pool:
            pool = free_pool
    if not pool:
        return None

    rank = VISION_RANK if ideal_profile == "vision" else (CREATIVE_RANK if ideal_profile == "creative" else FAST_RANK)
    scored = sorted(pool, key=lambda m: _score_model(m, rank, prefer_free=prefer_free, strict_free=False), reverse=True)
    return scored[0]


def build_recommendations(available_models: list[dict], current_overrides: dict[str, str] | None = None) -> dict:
    """Builds 'free', 'balanced', and 'pro' assignments + validates custom stage overrides."""
    by_key = {m["key"]: m for m in available_models}
    profiles: dict[str, dict[str, str]] = {"free": {}, "balanced": {}, "pro": {}}
    cost_estimates: dict[str, float] = {"free": 0.0, "balanced": 0.0, "pro": 0.0}
    warnings: list[str] = []

    has_any_vision = any(m["supports_vision"] for m in available_models)
    has_free_vision = any(m["supports_vision"] and m["is_free"] for m in available_models)

    if available_models and not has_any_vision:
        warnings.append(
            "Ninguno de los modelos detectados soporta VISIÓN. Conecta Google Gemini (gratis en AI Studio) u OpenRouter para los pasos 4 y 6."
        )
    elif available_models and not has_free_vision:
        warnings.append(
            "No se detectó un modelo GRATIS con Visión; el modo 100% Gratis usará el modelo con Visión más económico en los pasos 4 y 6."
        )

    for st in PIPELINE_STAGES:
        sid = st["id"]
        req_vis = st["requires_vision"]
        ideal = st["ideal_profile"]
        tokens_m = st["approx_tokens"] / 1_000_000.0

        # 1. Free Profile ($0 priority)
        m_free = _pick_best(available_models, req_vis, ideal, prefer_free=True, strict_free=True)
        if m_free:
            profiles["free"][sid] = m_free["key"]
            cost_estimates["free"] += m_free["price_per_1m_in"] * tokens_m

        # 2. Balanced Profile (Free for mechanical/fast steps, Best value/pro for Creative & Vision)
        use_free_here = ideal == "fast"
        m_bal = _pick_best(available_models, req_vis, ideal, prefer_free=use_free_here, strict_free=False)
        if m_bal:
            profiles["balanced"][sid] = m_bal["key"]
            cost_estimates["balanced"] += m_bal["price_per_1m_in"] * tokens_m

        # 3. Pro Profile (Top flagship capability per specialty)
        m_pro = _pick_best(available_models, req_vis, ideal, prefer_free=False, strict_free=False)
        if m_pro:
            profiles["pro"][sid] = m_pro["key"]
            cost_estimates["pro"] += m_pro["price_per_1m_in"] * tokens_m

    # Validate current_overrides if present
    validated_custom: dict[str, str] = {}
    if current_overrides:
        for st in PIPELINE_STAGES:
            sid = st["id"]
            chosen_key = current_overrides.get(sid, "")
            chosen_model = by_key.get(chosen_key)
            if chosen_model:
                if st["requires_vision"] and not chosen_model["supports_vision"]:
                    # Auto-protect Vision lock!
                    fallback = profiles["balanced"].get(sid) or profiles["free"].get(sid, "")
                    validated_custom[sid] = fallback
                else:
                    validated_custom[sid] = chosen_key
            elif sid in profiles["balanced"]:
                validated_custom[sid] = profiles["balanced"][sid]

    return {
        "stages": PIPELINE_STAGES,
        "profiles": profiles,
        "estimated_cost_usd_per_video": {k: round(v, 4) for k, v in cost_estimates.items()},
        "validated_custom": validated_custom,
        "warnings": warnings,
    }


def validate_stage_assignment(stage_id: str, model_meta: dict) -> tuple[bool, str]:
    stage = next((s for s in PIPELINE_STAGES if s["id"] == stage_id), None)
    if not stage:
        return False, f"Etapa desconocida: {stage_id}"
    if stage["requires_vision"] and not model_meta.get("supports_vision", False):
        return (
            False,
            f"La etapa '{stage['name']}' audita imágenes reales y exige un modelo con VISIÓN.",
        )
    return True, "OK"
