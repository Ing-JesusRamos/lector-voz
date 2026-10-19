"""Arranque de los workers (proceso separado) del lector de voz.

Cada worker consume su propio stream en su propio grupo:
  - extractores     -> documento.subido
  - sintetizadores  -> lectura.solicitada

Uso:  python -m workers.main
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Awaitable, Callable

import redis.exceptions as redis_exceptions

from app_events.broker import Broker
from app_events.contract import (
    GRUPO_EXTRACTORES,
    GRUPO_SINTETIZADORES,
    STREAM_DOCUMENTO_SUBIDO,
    STREAM_LECTURA_SOLICITADA,
)
from app_events.store import DocStore
from lector_core.extractor import DocumentExtractor
from lector_core.translate import MicrosoftTranslator
from lector_core.tts import VoiceSynthesizer
from workers.consumer_extract import ConsumerExtractor
from workers.consumer_tts import ConsumerTTS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
REGISTRO = logging.getLogger("workers")


async def bucle_consumidor(
    broker: Broker,
    stream: str,
    grupo: str,
    consumidor: str,
    procesar: Callable[[str, dict], Awaitable[None]],
) -> None:
    """Lee la fila del worker en bucle y procesa cada evento confirmándolo."""
    await broker.crear_grupo(stream, grupo)
    while True:
        try:
            mensajes = await broker.recuperar_pendientes(stream, grupo, consumidor)
            if not mensajes:
                mensajes = await broker.consumir(stream, grupo, consumidor)
        except (redis_exceptions.TimeoutError, redis_exceptions.ConnectionError, OSError):
            REGISTRO.warning("%s: Redis no responde, reintento en 1s", consumidor)
            await asyncio.sleep(1)
            continue
        for evento_id, payload in mensajes:
            try:
                await procesar(evento_id, payload)
            except Exception as error:
                REGISTRO.error("Falla en %s: %s", consumidor, error)
                # El mensaje queda pendiente para que XAUTOCLAIM lo reintente.
        await asyncio.sleep(0.05)


async def main() -> None:
    broker = Broker()
    store = DocStore(broker.redis)
    extractor = ConsumerExtractor(broker, store, DocumentExtractor())
    sintetizador = ConsumerTTS(
        broker, store, MicrosoftTranslator(), VoiceSynthesizer()
    )

    tareas = [
        bucle_consumidor(
            broker,
            STREAM_DOCUMENTO_SUBIDO,
            GRUPO_EXTRACTORES,
            f"{socket.gethostname()}-{os.getpid()}-extractor",
            extractor.procesar,
        ),
        bucle_consumidor(
            broker,
            STREAM_LECTURA_SOLICITADA,
            GRUPO_SINTETIZADORES,
            f"{socket.gethostname()}-{os.getpid()}-sintetizador",
            sintetizador.procesar,
        ),
    ]
    REGISTRO.info("Workers en marcha (extractores + sintetizadores)")
    try:
        await asyncio.gather(*tareas)
    finally:
        await broker.cerrar()


if __name__ == "__main__":
    asyncio.run(main())
