"""API del lector de voz: actúa como PRODUCTOR de eventos y expone la UI
(PWA) por SSE. Toda la lógica de extracción y síntesis vive en los workers.

Flujo:
  POST /api/upload  -> XADD documento.subido  (202 Aceptado al instante)
  POST /api/play    -> XADD lectura.solicitada (202 Aceptado al instante)
  GET  /api/events  -> SSE: la UI recibe documento.listolol y audio.listolol
  GET  /api/audio/**-> sirve el audio ya generado por el worker
"""
from __future__ import annotations

import json
import asyncio
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from app_events.broker import Broker
from app_events.contract import (
    CHANNEL_EVENTOS_PUBLICOS,
    STREAM_DOCUMENTO_SUBIDO,
    STREAM_LECTURA_SOLICITADA,
    documento_subido,
    lectura_solicitada,
)
from app_events.store import DocStore
from lector_core.translate import MicrosoftTranslator
from lector_core.tts import VoiceSynthesizer

load_dotenv()
app = FastAPI(title="Lector de voz (EDA)", version="0.2.0")

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "data" / "docs"
AUDIO_DIR = ROOT / "data" / "audio"
WEB_DIR = ROOT / "web"
DOCS_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

broker = Broker()
store = DocStore(broker.redis)
traductor = MicrosoftTranslator()

TIPOS_PERMITIDOS = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class PlayRequest(BaseModel):
    doc_id: str
    chunk_index: int
    target_lang: str = "es"
    voice: str | None = None


async def suscribir_ui() -> EventSourceResponse:
    """Escucha el canal público y reenvía cada evento a la UI como SSE."""

    async def flujo_eventos():
        pubsub = broker.redis.pubsub()
        await pubsub.subscribe(CHANNEL_EVENTOS_PUBLICOS)
        try:
            while True:
                mensaje = await pubsub.get_message(ignore_subscribe_messages=True)
                if mensaje:
                    evento = json.loads(mensaje["data"])
                    yield {
                        "event": evento["tipo"],
                        "data": json.dumps(evento["payload"], ensure_ascii=False),
                    }
                await asyncio.sleep(0.1)
        finally:
            await pubsub.unsubscribe(CHANNEL_EVENTOS_PUBLICOS)

    return EventSourceResponse(flujo_eventos(), ping=15)


@app.get("/api/events")
async def events():
    return await suscribir_ui()


# ---------------------------------------------------------------------------
# Productores
# ---------------------------------------------------------------------------

class UploadResponse(BaseModel):
    doc_id: str
    nombre: str
    aceptado: bool = True


@app.post("/api/upload", response_model=UploadResponse, status_code=202)
async def upload(archivo: UploadFile = File(...)):
    nombre = Path(archivo.filename or "").name
    extension = Path(nombre).suffix.lower()
    if extension not in {".pdf", ".docx"}:
        raise HTTPException(400, "Solo se aceptan PDF y Word .docx")
    if archivo.content_type not in TIPOS_PERMITIDOS | {"application/octet-stream"}:
        raise HTTPException(400, "Tipo de archivo no permitido")
    if not nombre:
        raise HTTPException(400, "El archivo debe tener nombre")

    doc_id = uuid.uuid4().hex[:12]
    ruta_fuente = DOCS_DIR / f"{doc_id}_{nombre}"
    bytes_recibidos = 0
    try:
        with ruta_fuente.open("wb") as destino:
            while bloque := archivo.file.read(1024 * 1024):
                bytes_recibidos += len(bloque)
                if bytes_recibidos > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "El archivo supera el límite de 25 MB")
                destino.write(bloque)
    except HTTPException:
        ruta_fuente.unlink(missing_ok=True)
        raise

    await broker.publicar(
        STREAM_DOCUMENTO_SUBIDO,
        documento_subido(doc_id, str(ruta_fuente), nombre),
    )
    return UploadResponse(doc_id=doc_id, nombre=nombre)


@app.post("/api/play", status_code=202)
async def play(body: PlayRequest):
    documento = await store.obtener_documento(body.doc_id)
    if not documento:
        raise HTTPException(404, "Documento no encontrado")
    if not 0 <= body.chunk_index < len(documento["chunks"]):
        raise HTTPException(400, "chunk_index fuera de rango")
    if body.target_lang != documento["idioma"] and not traductor.is_available:
        raise HTTPException(
            503,
            "La traducción no está configurada. Define AZURE_TRANSLATOR_KEY en .env.",
        )

    voz = body.voice or VoiceSynthesizer.best_voice_for(body.target_lang)
    await broker.publicar(
        STREAM_LECTURA_SOLICITADA,
        lectura_solicitada(body.doc_id, body.chunk_index, body.target_lang, voz),
    )
    return {"aceptado": True, "chunk_index": body.chunk_index}


# ---------------------------------------------------------------------------
# Consultas (el estado ya quedó guardado en Redis por los workers)
# ---------------------------------------------------------------------------

@app.get("/api/docs/{doc_id}")
async def obtener_documento(doc_id: str):
    documento = await store.obtener_documento(doc_id)
    if not documento:
        raise HTTPException(404, "Documento no encontrado")
    return documento


@app.get("/api/chunk-text/{doc_id}/{chunk_index}")
async def chunk_text(doc_id: str, chunk_index: int):
    documento = await store.obtener_documento(doc_id)
    if not documento:
        raise HTTPException(404, "Documento no encontrado")
    if not 0 <= chunk_index < len(documento["chunks"]):
        raise HTTPException(400, "chunk_index fuera de rango")
    return documento["chunks"][chunk_index]["text"]


@app.get("/api/voices")
async def voices():
    online = await VoiceSynthesizer.list_online_voices()
    return {
        "es": sorted(v["name"] for v in online if v["language"].lower().startswith("es-")),
        "en": sorted(v["name"] for v in online if v["language"].lower().startswith("en-")),
    }


@app.get("/api/translate/status")
def translate_status():
    return {"disponible": traductor.is_available}


@app.get("/api/audio/{nombre_archivo:path}")
async def servir_audio(nombre_archivo: str):
    ruta = (AUDIO_DIR / nombre_archivo).resolve()
    if ruta.parent != AUDIO_DIR.resolve() or not ruta.is_file():
        raise HTTPException(404, "Audio no generado todavía")
    return FileResponse(ruta, media_type=f"audio/{ruta.suffix.lstrip('.')}")


@app.get("/api/timings/{nombre_archivo:path}")
async def servir_timings(nombre_archivo: str):
    ruta = (AUDIO_DIR / nombre_archivo).resolve()
    if ruta.parent != AUDIO_DIR.resolve() or ruta.suffix != ".json" or not ruta.is_file():
        raise HTTPException(404, "Tiempos no generados todavía")
    return FileResponse(ruta, media_type="application/json")


@app.get("/health")
async def health():
    return {"ok": True, "traductor": traductor.is_available}


# ---------------------------------------------------------------------------
# Frontend PWA
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
