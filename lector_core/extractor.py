"""Extracción de contenido de PDF y Word a trozos (chunks) por párrafo."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil

import pymupdf
import pytesseract
from docx import Document
from PIL import Image

OCR_MIN_CHARS = 5
MAX_READING_CHARS = 900
TESSERACT_CANDIDATES = (
    "C:/Program Files/Tesseract-OCR/tesseract.exe",
    "C:/Program Files (x86)/Tesseract-OCR/tesseract.exe",
)


@dataclass
class Chunk:
    index: int
    text: str
    page: int | None = None

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


class DocumentExtractor:
    """Convierte un PDF/DOCX en unidades de lectura completas.

    Aplica OCR (Tesseract, idiomas es+eng) a las páginas de PDF que no
    tienen capa de texto (escaneadas).
    """

    def __init__(self, ocr_languages: str = "spa+eng") -> None:
        self._ocr_languages = ocr_languages
        self._tessdata_dir = Path(__file__).resolve().parents[1] / "data" / "tessdata"
        tesseract_path = shutil.which("tesseract") or next(
            (path for path in TESSERACT_CANDIDATES if Path(path).is_file()),
            None,
        )
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
        if self._tessdata_dir.is_dir():
            os.environ["TESSDATA_PREFIX"] = str(self._tessdata_dir)

    def extract(self, path: str | Path) -> list[Chunk]:
        documento = Path(path)
        if documento.suffix.lower() == ".pdf":
            return self._extract_pdf(documento)
        if documento.suffix.lower() in (".docx", ".doc"):
            return self._extract_docx(documento)
        raise ValueError(f"Formato no soportado: {documento.suffix}")

    def _extract_pdf(self, path: Path) -> list[Chunk]:
        chunks: list[Chunk] = []
        with pymupdf.open(path) as documento:
            for numero_pagina, pagina in enumerate(documento, start=1):
                texto = pagina.get_text().strip()
                if len(texto) < OCR_MIN_CHARS:
                    texto = self._ocr_page(pagina)
                for unidad in self._split_reading_units(texto):
                    chunks.append(Chunk(index=len(chunks), text=unidad, page=numero_pagina))
        return chunks

    def _extract_docx(self, path: Path) -> list[Chunk]:
        documento = Document(path)
        chunks: list[Chunk] = []
        for contenido in self._iter_text_blocks(documento):
            for unidad in self._split_reading_units(contenido):
                chunks.append(Chunk(index=len(chunks), text=unidad))
        return chunks

    def _iter_text_blocks(self, documento: Document):
        """Itera párrafos, e intercala las celdas de tablas entre ellos."""
        for parrafo in documento.paragraphs:
            texto = parrafo.text.strip()
            if texto:
                yield texto
        for tabla in documento.tables:
            for fila in tabla.rows:
                celdas = " | ".join(c.text.strip() for c in fila.cells)
                if celdas:
                    yield celdas

    def _ocr_page(self, page) -> str:
        pixmap = page.get_pixmap(dpi=300)
        imagen = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
        return pytesseract.image_to_string(imagen, lang=self._ocr_languages)

    @staticmethod
    def _split_reading_units(texto: str) -> list[str]:
        """Une saltos visuales y conserva frases completas para TTS natural."""
        normalizado = re.sub(r"\s+", " ", texto).strip()
        if not normalizado:
            return []

        frases = [
            frase.strip()
            for frase in re.split(r"(?<=[.!?。！？])\s+", normalizado)
            if frase.strip()
        ]
        unidades: list[str] = []
        actual = ""
        for frase in frases:
            propuesta = f"{actual} {frase}".strip()
            if actual and len(propuesta) > MAX_READING_CHARS:
                unidades.append(actual)
                actual = frase
            else:
                actual = propuesta
        if actual:
            unidades.append(actual)

        resultado: list[str] = []
        for unidad in unidades:
            if len(unidad) <= MAX_READING_CHARS:
                resultado.append(unidad)
                continue
            resultado.extend(
                parte.strip()
                for parte in re.split(r"(?<=[,;:])\s+", unidad)
                if parte.strip()
            )
        return resultado
