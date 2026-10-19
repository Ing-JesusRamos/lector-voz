"""Estado de documentos en Redis: lo escriben los workers (al extraer) y
lo leen la API (para mostrar texto y la síntesis usa los chunks guardados).
"""
from __future__ import annotations

import json

from redis.asyncio import Redis


class DocStore:
    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def guardar_documento(
        self,
        doc_id: str,
        idioma: str,
        chunks: list[dict],
    ) -> None:
        await self._redis.hset(
            f"doc:{doc_id}",
            mapping={
                "idioma": idioma,
                "chunks": json.dumps(chunks, ensure_ascii=False),
            },
        )

    async def obtener_documento(self, doc_id: str) -> dict | None:
        datos = await self._redis.hgetall(f"doc:{doc_id}")
        if not datos:
            return None
        return {
            "idioma": datos["idioma"],
            "chunks": json.loads(datos["chunks"]),
        }