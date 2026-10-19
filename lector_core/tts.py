"""Síntesis de voz: edge-tts (online, neural) con fallback offline pyttsx4."""
from __future__ import annotations

import re
from typing import Iterable
from pathlib import Path

import edge_tts


class VoiceSynthesizer:
    """Genera archivos de audio MP3/WAV a partir de texto y voz."""

    FALLBACK_VOICES = [
        {"name": "es-MX-DaliaNeural", "language": "es-MX"},
        {"name": "es-MX-JorgeNeural", "language": "es-MX"},
        {"name": "es-ES-ElviraNeural", "language": "es-ES"},
        {"name": "es-ES-AlvaroNeural", "language": "es-ES"},
        {"name": "en-US-AriaNeural", "language": "en-US"},
        {"name": "en-US-JennyNeural", "language": "en-US"},
        {"name": "en-US-GuyNeural", "language": "en-US"},
        {"name": "en-GB-SoniaNeural", "language": "en-GB"},
    ]

    async def synthesize_edge(self, text: str, voice: str, destino: str | Path) -> None:
        """Sintetiza con edge-tts y guarda MP3. Lanza excepción si falla.

        Debe ejecutarse dentro de un event loop (consumer async), igual que
        edge-tts (cliente websocket asíncrono).
        """
        comunicador = edge_tts.Communicate(text, voice)
        await comunicador.save(str(destino))

    async def synthesize_edge_with_timings(
        self,
        text: str,
        voice: str,
        destino: str | Path,
    ) -> list[dict[str, float | str]]:
        """Genera un audio continuo y sus límites temporales por palabra."""
        comunicador = edge_tts.Communicate(text, voice, boundary="WordBoundary")
        timings: list[dict[str, float | str]] = []
        with Path(destino).open("wb") as audio:
            async for mensaje in comunicador.stream():
                if mensaje["type"] == "audio":
                    audio.write(mensaje["data"])
                elif mensaje["type"] == "WordBoundary":
                    timings.append(
                        {
                            "text": mensaje["text"],
                            "start": mensaje["offset"] / 10_000_000,
                            "end": (mensaje["offset"] + mensaje["duration"]) / 10_000_000,
                        }
                    )
        return timings

    @staticmethod
    def estimate_timings(
        chunks: Iterable[str], duration: float,
    ) -> list[dict[str, float | str]]:
        """Crea cues aproximados para el fallback offline sin metadatos TTS."""
        words = [word for chunk in chunks for word in re.findall(r"\S+", chunk)]
        if not words:
            return []
        weight = [max(len(word), 1) for word in words]
        total = sum(weight)
        cursor = 0.0
        timings = []
        for word, size in zip(words, weight):
            end = cursor + duration * size / total
            timings.append({"text": word, "start": cursor, "end": end})
            cursor = end
        return timings

    def synthesize_offline(self, text: str, destino: str | Path) -> None:
        """Sintetiza con pyttsx4 (SAPI5 en Windows) y guarda WAV."""
        import pyttsx4

        motor = pyttsx4.init()
        motor.setProperty("rate", 180)
        motor.save_to_file(text, str(destino))
        motor.runAndWait()

    @staticmethod
    async def list_online_voices() -> list[dict]:
        """Devuelve las voces de edge-tts disponibles (nombre + idioma)."""
        try:
            voces = await edge_tts.list_voices()
            return [{"name": v["ShortName"], "language": v["Locale"]} for v in voces]
        except Exception:
            # La selección sigue disponible aunque el catálogo online falle.
            return VoiceSynthesizer.FALLBACK_VOICES

    @staticmethod
    def best_voice_for(language: str) -> str:
        """Voz por defecto según el idioma de lectura (es/en)."""
        catalogo = {
            "es": "es-MX-DaliaNeural",
            "en": "en-US-AriaNeural",
        }
        return catalogo.get(language, "es-MX-DaliaNeural")
