"""Consumidor: sintetiza el audio de un chunk solicitado.

Escucha lectura.solicitada, traduce el texto si el idioma pedido difiere
del documento (y hay traductor configurado), genera el MP3/WAV en caché y
publica audio.listololo con la URL para que la UI lo reproduzca.
"""
from __future__ import annotations

import logging
import asyncio
import hashlib
import json
import re
import wave
from pathlib import Path

from app_events.broker import Broker
from app_events.contract import (
    GRUPO_SINTETIZADORES,
    STREAM_AUDIO_LISTO,
    STREAM_LECTURA_SOLICITADA,
    audio_listo,
)
from app_events.store import DocStore
from lector_core.translate import MicrosoftTranslator
from lector_core.tts import VoiceSynthesizer

REGISTRO = logging.getLogger("consumer_tts")
RAIZ = Path(__file__).resolve().parent.parent
AUDIO_DIR = RAIZ / "data" / "audio"


class ConsumerTTS:
    def __init__(
        self,
        broker: Broker,
        store: DocStore,
        traductor: MicrosoftTranslator,
        sintetizador: VoiceSynthesizer,
    ) -> None:
        self._broker = broker
        self._store = store
        self._traductor = traductor
        self._sintetizador = sintetizador

    async def procesar(self, evento_id: str, payload: dict) -> None:
        doc_id = payload["doc_id"]
        indice = int(payload["chunk_index"])
        idioma_destino = payload["target_lang"]
        voz = payload["voz"] or VoiceSynthesizer.best_voice_for(idioma_destino)

        documento = await self._store.obtener_documento(doc_id)
        if not documento:
            raise KeyError(f"{doc_id}: documento desconocido")

        if not 0 <= indice < len(documento["chunks"]):
            raise ValueError(f"{doc_id}: chunk_index fuera de rango: {indice}")

        # Sintetiza solo el bloque solicitado; la UI precarga el siguiente para
        # que el usuario no tenga que esperar la generación de todo el documento.
        chunks = documento["chunks"][indice:indice + 1]
        spoken_chunks = [chunk["text"] for chunk in chunks]
        tradujo = False
        if idioma_destino != documento["idioma"] and self._traductor.is_available:
            spoken_chunks = [
                await asyncio.to_thread(
                    self._traductor.translate, chunk, idioma_destino, documento["idioma"]
                )
                for chunk in spoken_chunks
            ]
            tradujo = True

        voice_id = hashlib.sha1(voz.encode("utf-8")).hexdigest()[:8]
        base_name = f"{doc_id}-{idioma_destino}-{indice}-{voice_id}"
        audio = AUDIO_DIR / f"{base_name}.mp3"
        timings_path = AUDIO_DIR / f"{base_name}.json"
        if not audio.exists() or not timings_path.exists():
            text = "\n\n".join(spoken_chunks)
            try:
                timings = await self._sintetizador.synthesize_edge_with_timings(text, voz, audio)
            except Exception:
                # edge-tts puede dejar un archivo parcial antes de fallar.
                audio.unlink(missing_ok=True)
                audio = audio.with_suffix(".wav")
                await asyncio.to_thread(self._sintetizador.synthesize_offline, text, audio)
                with wave.open(str(audio), "rb") as wav_file:
                    duration = wav_file.getnframes() / wav_file.getframerate()
                timings = self._sintetizador.estimate_timings(spoken_chunks, duration)

            word_offset = sum(
                len(re.findall(r"\S+", chunk["text"]))
                for chunk in documento["chunks"][:indice]
            )
            self._assign_chunk_indexes(timings, spoken_chunks, indice, word_offset)
            timings_path = audio.with_suffix(".json")
            timings_path.write_text(
                json.dumps({"chunks": spoken_chunks, "words": timings}, ensure_ascii=False),
                encoding="utf-8",
            )

        url_audio = f"/api/audio/{audio.name}"
        timings_url = f"/api/timings/{timings_path.name}"
        await self._broker.publicar(
            STREAM_AUDIO_LISTO,
            audio_listo(doc_id, indice, url_audio, tradujo, timings_url),
        )
        await self._broker.confirmar(STREAM_LECTURA_SOLICITADA, GRUPO_SINTETIZADORES, evento_id)
        REGISTRO.info("%s chunk %s listo (%s)", doc_id, indice, url_audio)

    @staticmethod
    def _assign_chunk_indexes(
        timings: list[dict],
        chunks: list[str],
        chunk_offset: int = 0,
        word_offset: int = 0,
    ) -> None:
        word_limits = [len(re.findall(r"\S+", chunk)) for chunk in chunks]
        chunk_index = 0
        words_in_chunk = 0
        for word_index, timing in enumerate(timings):
            while chunk_index < len(word_limits) - 1 and words_in_chunk >= word_limits[chunk_index]:
                chunk_index += 1
                words_in_chunk = 0
            timing["word_index"] = word_offset + word_index
            timing["chunk_index"] = chunk_offset + chunk_index
            words_in_chunk += 1
