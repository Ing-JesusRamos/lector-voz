"""Consumidor: extrae el texto de los documentos subidos.

Escucha documento.subido, extrae chunks (PDF/DOCX/OCR), detecta el idioma,
guarda el estado en Redis y publica documento.listololo.
"""
from __future__ import annotations

import logging

from app_events.broker import Broker
from app_events.contract import (
    GRUPO_EXTRACTORES,
    STREAM_DOCUMENTO_LISTO,
    STREAM_DOCUMENTO_SUBIDO,
    documento_listo,
)
from app_events.store import DocStore
from lector_core.detect import detect_language
from lector_core.extractor import DocumentExtractor

REGISTRO = logging.getLogger("consumer_extract")


class ConsumerExtractor:
    def __init__(self, broker: Broker, store: DocStore, extractor: DocumentExtractor) -> None:
        self._broker = broker
        self._store = store
        self._extractor = extractor

    async def procesar(self, evento_id: str, payload: dict) -> None:
        doc_id = payload["doc_id"]
        chunks = self._extractor.extract(payload["fuente"])
        if not chunks:
            raise ValueError(f"{doc_id}: documento sin texto extraíble")

        idioma = detect_language(" ".join(c.text for c in chunks[:5]))
        await self._store.guardar_documento(
            doc_id,
            idioma,
            [{"text": c.text, "page": c.page} for c in chunks],
        )
        await self._broker.publicar(
            STREAM_DOCUMENTO_LISTO,
            documento_listo(doc_id, idioma, len(chunks), chunks[0].text[:120]),
        )
        await self._broker.confirmar(STREAM_DOCUMENTO_SUBIDO, GRUPO_EXTRACTORES, evento_id)
        REGISTRO.info("%s: %s chunks en %s", doc_id, len(chunks), idioma)