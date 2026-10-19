# Lector de voz (EDA)

PWA + FastAPI que lee documentos PDF/Word en voz alta (es/en), con traducción
opcional y arquitectura **basada en eventos**: la API publica eventos en Redis
Streams y unos workers aparte extraen el texto y sintetizan el audio.

## Arquitectura

```
API (productor)            Broker Redis          Workers (proceso aparte)
POST /api/upload ──► XADD documento.subido ──► [extractor] extrae + detecta idioma
POST /api/play   ──► XADD lectura.solicitada ─► [sintetizador] traduce + genera audio
UI (PWA) ◄──────────── Pub/Sub → SSE (/api/events) ◄─────────────── audio.listolol
```

- **`app_events/contract.py`** — única fuente de verdad de los eventos
  (streams, grupos y payloads). `broker.py` publica/consume; `store.py` guarda
  el estado del documento en Redis.
- **`api/`** — FastAPI como **productor**: responde 202 al instante y expone
  `/api/events` (SSE) para la PWA.
- **`workers/`** — **consumidores** en proceso separado: extracción y síntesis.
  `python -m workers.main`
- **`lector_core/`** — lógica pura compartida (extraer, detectar, traducir, voz).
- **`web/`** — PWA (HTML+JS+manifest+service worker).

## Arranque

```bash
# 1. Redis en Windows:
# Instala Memurai Developer y déjalo ejecutándose como servicio.
# Este proyecto usa Redis Streams y no requiere Docker.

# 2. Dependencias:
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt

# 3. Workers (proceso separado):
python -m workers.main

# 4. API + PWA:
cp .env.example .env    # rellena AZURE_TRANSLATOR_KEY si quieres traducción
uvicorn api.main:app --reload
```

Abre http://localhost:8000, sube un PDF/Word y pulsa *▶ Leer*.

## Traducción

Sin clave de Azure la app lee el documento en su idioma original.
Con `AZURE_TRANSLATOR_KEY` (tier gratuito) traduce ES<->EN automáticamente
según el idioma de lectura elegido. Límite F0: 2M caracteres/mes.

Para activar la traducción localmente, crea `.env` a partir de `.env.example`
y define `AZURE_TRANSLATOR_KEY` y `AZURE_TRANSLATOR_REGION`. Sin esa clave,
la interfaz informa que la traducción no está disponible y no envía una
solicitud que produciría una voz inglesa pronunciando texto español.

## OCR

El extractor usa Tesseract para PDF escaneados. En Windows, instala Tesseract
5.x y asegúrate de que el ejecutable esté en `C:\Program Files\Tesseract-OCR`.
Los modelos `eng` y `spa` se buscan en `data/tessdata/`; el directorio está
ignorado por git porque contiene binarios descargados localmente.
