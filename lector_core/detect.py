"""Detección de idioma por trozo de texto."""
from __future__ import annotations

from langdetect import detect

FALLBACK_LANG = "es"


def detect_language(text: str) -> str:
    """Devuelve el código ISO-639 del idioma dominante (es, en, ...)."""
    try:
        return detect(text)
    except Exception:
        return FALLBACK_LANG