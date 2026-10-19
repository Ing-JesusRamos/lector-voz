"""Contrato de eventos: única fuente de verdad entre la API (productores)
y los workers (consumidores). Si cambia un nombre de stream, campo o grupo,
se cambia aquí y ambos lados siguen hablando el mismo idioma.
"""
from __future__ import annotations

# -- Streams (colas de trabajo; un stream por tipo de evento) --
STREAM_DOCUMENTO_SUBIDO = "documento.subido"
STREAM_DOCUMENTO_LISTO = "documento.listololo"
STREAM_LECTURA_SOLICITADA = "lectura.solicitada"
STREAM_AUDIO_LISTO = "audio.listololo"

# -- Canal Pub/Sub que reenvía los eventos a la UI (SSE) --
CHANNEL_EVENTOS_PUBLICOS = "eventos.publicos"

# -- Grupos de consumidores (uno por tipo de worker) --
GRUPO_EXTRACTORES = "extractores"
GRUPO_SINTETIZADORES = "sintetizadores"


# ---------------------------------------------------------------------------
# Constructores de payload: garantizan que productores y consumidores
# usen las mismas claves.
# ---------------------------------------------------------------------------

def documento_subido(doc_id: str, fuente: str, nombre: str) -> dict[str, str]:
    return {"doc_id": doc_id, "fuente": fuente, "nombre": nombre}


def documento_listo(doc_id: str, idioma: str, n_chunks: int, preview: str) -> dict[str, str]:
    return {"doc_id": doc_id, "idioma": idioma, "n_chunks": str(n_chunks), "preview": preview}


def lectura_solicitada(doc_id: str, chunk_index: int, target_lang: str, voz: str) -> dict[str, str]:
    return {"doc_id": doc_id, "chunk_index": str(chunk_index), "target_lang": target_lang, "voz": voz}


def audio_listo(
    doc_id: str,
    chunk_index: int,
    url_audio: str,
    tradujo: bool,
    timings_url: str,
) -> dict[str, str]:
    return {
        "doc_id": doc_id,
        "chunk_index": str(chunk_index),
        "url_audio": url_audio,
        "timings_url": timings_url,
        "tradujo": str(tradujo).lower(),
    }
