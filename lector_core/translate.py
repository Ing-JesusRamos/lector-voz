"""Traducción vía Microsoft Translator (tier gratuito F0, 2M caracteres/mes).

La clave se lee de la variable de entorno AZURE_TRANSLATOR_KEY. Sin clave
la app no traduce: devuelve el texto original (la lectura no se bloquea).
"""
from __future__ import annotations

import os

import requests

URL_BASE = "https://api.cognitive.microsofttranslator.com/translate"
API_VERSION = "3.0"


class MicrosoftTranslator:
    def __init__(
        self,
        key: str | None = None,
        region: str | None = None,
        base_url: str = URL_BASE,
    ) -> None:
        self._key = key or os.getenv("AZURE_TRANSLATOR_KEY")
        self._region = region or os.getenv("AZURE_TRANSLATOR_REGION", "westus2")
        self._base_url = base_url

    @property
    def is_available(self) -> bool:
        return bool(self._key)

    def translate(
        self,
        text: str,
        target_lang: str,
        source_hint: str | None = None,
    ) -> str:
        """Traduce `text` al idioma destino; sin clave, devuelve el original."""
        if not self.is_available:
            return text
        params = {"api-version": API_VERSION, "to": target_lang}
        if source_hint:
            params["from"] = source_hint
        respuesta = requests.post(
            self._base_url,
            params=params,
            json=[{"text": text}],
            headers={
                "Ocp-Apim-Subscription-Key": self._key,
                "Ocp-Apim-Subscription-Region": self._region,
                "Content-Type": "application/json",
            },
            timeout=20,
        )
        respuesta.raise_for_status()
        return respuesta.json()[0]["translations"][0]["text"]