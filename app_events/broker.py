"""Broker Redis asíncrono: publica eventos (XADD + Pub/Sub) y los consume
con grupos de consumidores (XREADGROUP), como lo documenta redis-streams.
"""
from __future__ import annotations

import json
import os

import redis.asyncio as aioredis

from app_events.contract import CHANNEL_EVENTOS_PUBLICOS


class Broker:
    """Abstrae Redis como bróker de eventos para productores y consumidores."""

    def __init__(self, url: str | None = None) -> None:
        url = url or os.getenv("REDIS_URL", "redis://localhost:6379")
        # protocol=2: Memurai no implementa los push mensajes de RESP3 en
        # comandos bloqueantes (XREADGROUP BLOCK) y redis-py 8+ usa RESP3
        # por defecto, provocando timeouts. RESP2 es estable en ambos.
        self._redis = aioredis.from_url(url, decode_responses=True, protocol=2)

    @property
    def redis(self) -> aioredis.Redis:
        """Cliente compartido para que DocStore use la misma conexión."""
        return self._redis

    async def publicar(self, stream: str, payload: dict) -> str:
        """Añade un evento al stream (productor) y lo difunde a la UI."""
        evento_id = await self._redis.xadd(stream, payload)
        await self._redis.publish(
            CHANNEL_EVENTOS_PUBLICOS,
            json.dumps({"tipo": stream, "payload": payload}, ensure_ascii=False),
        )
        return evento_id

    async def crear_grupo(self, stream: str, grupo: str) -> None:
        """Crea el grupo de consumidores del stream (idempotente)."""
        try:
            await self._redis.xgroup_create(stream, grupo, id="0", mkstream=True)
        except aioredis.ResponseError:
            pass

    async def consumir(
        self,
        stream: str,
        grupo: str,
        consumidor: str,
        count: int = 10,
        block: int = 2000,
    ) -> list[tuple[str, dict]]:
        """Devuelve mensajes nuevos para el consumidor (bloquea hasta block ms)."""
        respuesta = await self._redis.xreadgroup(
            grupo, consumidor, {stream: ">"}, count=count, block=block
        )
        mensajes: list[tuple[str, dict]] = []
        for _, items in respuesta:
            for evento_id, payload in items:
                mensajes.append((evento_id, payload))
        return mensajes

    async def recuperar_pendientes(
        self,
        stream: str,
        grupo: str,
        consumidor: str,
        min_idle_time: int = 60_000,
        count: int = 10,
    ) -> list[tuple[str, dict]]:
        """Recupera mensajes abandonados por workers que dejaron de vivir."""
        _, items, _ = await self._redis.xautoclaim(
            stream,
            grupo,
            consumidor,
            min_idle_time,
            start_id="0-0",
            count=count,
        )
        return items

    async def confirmar(self, stream: str, grupo: str, evento_id: str) -> None:
        """Confirma el mensaje en el grupo tras procesarlo."""
        await self._redis.xack(stream, grupo, evento_id)

    async def cerrar(self) -> None:
        await self._redis.aclose()
