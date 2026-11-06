#!/usr/bin/env python3
"""
Live Neural Voice Audition Manager (Edge-TTS).
Generates & caches crystal-clear voice previews for the 8 official channel voices
so users can click '▶ Escuchar' inside the Post-Install Wizard.
"""
from __future__ import annotations

from pathlib import Path
import edge_tts

from src.backend.app_paths import get_appdata_dir

OFFICIAL_VOICES = [
    {
        "id": "es-MX-JorgeNeural",
        "name": "Jorge (México)",
        "lang": "es",
        "gender": "Masculina",
        "tone": "Profunda, intrigante, autoritaria",
        "recommended_niches": "Finanzas, Misterios, Historia Oculta, Crímenes",
        "sample_text": "El noventa por ciento de las personas ignora este secreto financiero hasta que es demasiado tarde.",
    },
    {
        "id": "es-ES-AlvaroNeural",
        "name": "Álvaro (España)",
        "lang": "es",
        "gender": "Masculina",
        "tone": "Sobria, documental periodístico",
        "recommended_niches": "Geopolítica, Ciencia, Estrategia, Tecnología",
        "sample_text": "Durante décadas, este documento clasificado permaneció oculto bajo el hielo del Ártico.",
    },
    {
        "id": "es-MX-DaliaNeural",
        "name": "Dalia (México)",
        "lang": "es",
        "gender": "Femenina",
        "tone": "Cálida, envolvente, altísima retención",
        "recommended_niches": "Psicología, Curiosidades, Hábitos, Salud",
        "sample_text": "Tu cerebro toma esta decisión en menos de medio segundo antes de que tú te des cuenta.",
    },
    {
        "id": "es-ES-ElviraNeural",
        "name": "Elvira (España)",
        "lang": "es",
        "gender": "Femenina",
        "tone": "Dinámica, segura, profesional",
        "recommended_niches": "Emprendimiento, Tendencias IA, Productividad",
        "sample_text": "Tres herramientas nuevas acaban de cambiar por completo la forma de trabajar desde casa.",
    },
    {
        "id": "en-US-ChristopherNeural",
        "name": "Christopher (US Tier-1)",
        "lang": "en",
        "gender": "Male",
        "tone": "Cinematic, deep storytelling authority",
        "recommended_niches": "Wealth, Dark Psychology, True Crime, Mysteries",
        "sample_text": "Ninety-nine percent of people walk past this hidden signal every single day without noticing.",
    },
    {
        "id": "en-GB-RyanNeural",
        "name": "Ryan (UK Documentary)",
        "lang": "en",
        "gender": "Male",
        "tone": "Prestigious BBC-style documentary",
        "recommended_niches": "History, Geopolitics, Luxury, Science",
        "sample_text": "For over a century, engineers believed building a structure like this was physically impossible.",
    },
    {
        "id": "en-US-JennyNeural",
        "name": "Jenny (US High-CTR)",
        "lang": "en",
        "gender": "Female",
        "tone": "Crisp, energetic, viral hook specialist",
        "recommended_niches": "Tech, AI Trends, Life Hacks, Psychology",
        "sample_text": "Stop scrolling for five seconds, because this tiny habit rewires your focus overnight.",
    },
    {
        "id": "en-US-AriaNeural",
        "name": "Aria (US Narrative)",
        "lang": "en",
        "gender": "Female",
        "tone": "Warm, emotional, deep storytelling",
        "recommended_niches": "Human Stories, Mindset, Health, Secrets",
        "sample_text": "Nobody expected what scientists discovered when they opened the sealed chamber.",
    },
]


def list_official_voices(lang: str | None = None) -> list[dict]:
    if not lang:
        return OFFICIAL_VOICES
    return [v for v in OFFICIAL_VOICES if v["lang"] == lang.lower()]


async def synthesize_voice_sample(voice_id: str) -> Path:
    voice_meta = next((v for v in OFFICIAL_VOICES if v["id"] == voice_id), OFFICIAL_VOICES[0])
    out_dir = get_appdata_dir() / "voice_samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{voice_meta['id']}.mp3"

    if out_file.exists() and out_file.stat().st_size > 1024:
        return out_file

    communicate = edge_tts.Communicate(voice_meta["sample_text"], voice_meta["id"], rate="+4%")
    await communicate.save(str(out_file))
    return out_file
