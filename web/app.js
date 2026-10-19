"use strict";

const estado = document.getElementById("estado");
const controles = document.getElementById("controles");
const selectIdiomaDoc = document.getElementById("idioma-doc");
const selectIdiomaLectura = document.getElementById("idioma-lectura");
const selectVoz = document.getElementById("voz");
const selectVelocidad = document.getElementById("velocidad");
const textoDocumento = document.getElementById("texto-documento");
const botonPlay = document.getElementById("play");
const botonAnterior = document.getElementById("anterior");
const botonSiguiente = document.getElementById("siguiente");
const progreso = document.getElementById("progreso");
const barraProgreso = document.getElementById("barra-progreso");
const indicadorLectura = document.getElementById("indicador-lectura");
const audio = document.getElementById("audio");
const eventos = new EventSource("/api/events");

let docId = null;
let nChunks = 0;
let indice = 0;
let idiomaDocumento = null;
let traduccionDisponible = false;
let voces = { es: [], en: [] };
let documentoChunks = [];
let cues = [];
let palabras = [];
let cueActual = -1;
let palabraActiva = -1;
let ultimoScroll = 0;
const audioCache = new Map();
const solicitudes = new Set();

function mostrarEstado(mensaje, tipo = "") {
  estado.textContent = mensaje;
  estado.className = `status-message ${tipo}`.trim();
}

function setIndicador(mensaje, activo = false) {
  indicadorLectura.classList.toggle("is-reading", activo);
  indicadorLectura.lastElementChild.textContent = mensaje;
}

function actualizarBoton() {
  if (!audio.src) botonPlay.textContent = "Leer";
  else if (!audio.paused) botonPlay.textContent = "Pausar";
  else if (audio.currentTime > 0 && !audio.ended) botonPlay.textContent = "Reanudar";
  else botonPlay.textContent = "Leer";
}

async function cargarVoces() {
  try {
    const respuesta = await fetch("/api/voices");
    if (!respuesta.ok) throw new Error("No se pudieron cargar las voces");
    voces = await respuesta.json();
    llenarVoces();
  } catch (error) {
    selectVoz.replaceChildren(new Option("Voz predeterminada", ""));
    mostrarEstado(error.message, "error");
  }
}

async function cargarEstadoTraduccion() {
  try {
    const respuesta = await fetch("/api/translate/status");
    const datos = await respuesta.json();
    traduccionDisponible = Boolean(datos.disponible);
  } catch {
    traduccionDisponible = false;
  }
}

function llenarVoces() {
  const disponibles = voces[selectIdiomaLectura.value] || [];
  selectVoz.replaceChildren();
  if (!disponibles.length) {
    selectVoz.add(new Option("Voz predeterminada", ""));
    return;
  }
  disponibles.forEach((voz) => selectVoz.add(new Option(voz, voz)));
}

function renderizarTexto(chunks) {
  palabras = [];
  palabraActiva = -1;
  textoDocumento.replaceChildren();
  chunks.forEach((chunk, chunkIndex) => {
    const parrafo = document.createElement("p");
    parrafo.className = "reader-chunk";
    parrafo.dataset.chunkIndex = chunkIndex;
    const tokens = chunk.text.match(/\s+|\S+/g) || [];
    tokens.forEach((token) => {
      if (/^\s+$/.test(token)) {
        parrafo.appendChild(document.createTextNode(token));
        return;
      }
      const palabra = document.createElement("span");
      palabra.className = "reader-word";
      palabra.textContent = token;
      palabra.dataset.wordIndex = palabras.length;
      palabras.push(palabra);
      parrafo.appendChild(palabra);
    });
    textoDocumento.appendChild(parrafo);
  });
}

async function subirArchivo(archivo) {
  mostrarEstado("Subiendo documento…");
  const form = new FormData();
  form.append("archivo", archivo);
  const respuesta = await fetch("/api/upload", { method: "POST", body: form });
  const datos = await respuesta.json();
  if (!respuesta.ok) throw new Error(datos.detail || "No se pudo subir el documento");

  docId = datos.doc_id;
  nChunks = 0;
  indice = 0;
  idiomaDocumento = null;
  documentoChunks = [];
  audioCache.clear();
  solicitudes.clear();
  cues = [];
  audio.pause();
  audio.removeAttribute("src");
  controles.hidden = false;
  textoDocumento.textContent = "Preparando el texto…";
  setIndicador("Procesando", false);
  actualizarBoton();
  mostrarEstado(`${datos.nombre} está siendo preparado.`);
}

async function cargarDocumento() {
  const respuesta = await fetch(`/api/docs/${docId}`);
  if (!respuesta.ok) throw new Error("No se pudo cargar el documento");
  const documento = await respuesta.json();
  documentoChunks = documento.chunks;
  nChunks = documentoChunks.length;
  renderizarTexto(documentoChunks);
  actualizarNavegacion();
}

function actualizarNavegacion() {
  progreso.textContent = `${indice + 1} de ${nChunks}`;
  barraProgreso.style.width = `${nChunks ? ((indice + 1) / nChunks) * 100 : 0}%`;
  botonAnterior.disabled = indice === 0;
  botonSiguiente.disabled = indice >= nChunks - 1;
}

eventos.addEventListener("documento.listololo", async (evento) => {
  const datos = JSON.parse(evento.data);
  if (datos.doc_id !== docId) return;
  indice = 0;
  idiomaDocumento = datos.idioma;
  selectIdiomaDoc.textContent = datos.idioma.toUpperCase();
  try {
    await cargarDocumento();
    mostrarEstado(`Documento listo. ${nChunks} bloque${nChunks === 1 ? "" : "s"}.`);
  } catch (error) {
    mostrarEstado(error.message, "error");
  }
});

async function prepararAudio(datos) {
  try {
    const respuesta = await fetch(datos.timings_url);
    if (!respuesta.ok) throw new Error("No se pudieron cargar los tiempos del audio");
    const metadatos = await respuesta.json();
    cues = metadatos.words || [];
    cueActual = -1;
    if (palabraActiva >= 0 && palabras[palabraActiva]) palabras[palabraActiva].classList.remove("is-active");
    palabraActiva = -1;
    audio.src = datos.url_audio;
    audio.playbackRate = Number(selectVelocidad.value);
    audio.currentTime = 0;
    audio.play().catch(() => {
      actualizarBoton();
      setIndicador("Audio listo", false);
      mostrarEstado("El audio está listo. Pulsa Leer para comenzar.", "error");
    });
  } catch (error) {
    mostrarEstado(error.message, "error");
  }
}

eventos.addEventListener("audio.listololo", (evento) => {
  const datos = JSON.parse(evento.data);
  if (datos.doc_id !== docId) return;
  const chunkIndex = Number(datos.chunk_index);
  audioCache.set(chunkIndex, datos);
  solicitudes.delete(chunkIndex);
  if (chunkIndex === indice) prepararAudio(datos);
});

function publicarSolicitud(chunkIndex, anunciar = true) {
  if (chunkIndex < 0 || chunkIndex >= nChunks || solicitudes.has(chunkIndex)) return;
  if (idiomaDocumento && selectIdiomaLectura.value !== idiomaDocumento && !traduccionDisponible) {
    mostrarEstado("La traducción no está disponible. Configura AZURE_TRANSLATOR_KEY en .env.", "error");
    return;
  }
  const body = {
    doc_id: docId,
    chunk_index: chunkIndex,
    target_lang: selectIdiomaLectura.value,
    voice: selectVoz.value,
  };
  solicitudes.add(chunkIndex);
  if (anunciar) setIndicador("Preparando audio", false);
  fetch("/api/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(async (respuesta) => {
    if (!respuesta.ok) {
      const datos = await respuesta.json();
      throw new Error(datos.detail || "No se pudo solicitar el audio");
    }
    if (anunciar) mostrarEstado("Preparando el siguiente bloque…");
  }).catch((error) => {
    solicitudes.delete(chunkIndex);
    if (anunciar) mostrarEstado(error.message, "error");
  });
}

function precargarSiguiente() {
  if (indice < nChunks - 1 && !audioCache.has(indice + 1)) publicarSolicitud(indice + 1, false);
}

function actualizarPalabraActual() {
  if (!cues.length) return;
  let nuevoIndice = cueActual;
  while (nuevoIndice + 1 < cues.length && audio.currentTime >= cues[nuevoIndice + 1].start) nuevoIndice += 1;
  while (nuevoIndice >= 0 && audio.currentTime < cues[nuevoIndice].start) nuevoIndice -= 1;
  if (nuevoIndice === cueActual || nuevoIndice < 0) return;

  if (palabraActiva >= 0 && palabras[palabraActiva]) palabras[palabraActiva].classList.remove("is-active");
  cueActual = nuevoIndice;
  palabraActiva = Number(cues[cueActual].word_index);
  const palabra = palabras[palabraActiva];
  if (!palabra) return;
  palabra.classList.add("is-active");
  indice = Number(cues[cueActual].chunk_index);
  actualizarNavegacion();
  const ahora = performance.now();
  if (ahora - ultimoScroll > 180) {
    palabra.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
    ultimoScroll = ahora;
  }
}

selectIdiomaLectura.addEventListener("change", () => {
  llenarVoces();
  audio.pause();
  audio.removeAttribute("src");
  audioCache.clear();
  solicitudes.clear();
  cues = [];
  actualizarBoton();
  setIndicador("Listo para leer", false);
});

selectVoz.addEventListener("change", () => {
  audio.pause();
  audio.removeAttribute("src");
  audioCache.clear();
  solicitudes.clear();
  cues = [];
  actualizarBoton();
  setIndicador("Listo para leer", false);
});

selectVelocidad.addEventListener("change", () => {
  audio.playbackRate = Number(selectVelocidad.value);
});

botonPlay.addEventListener("click", () => {
  if (!docId) return;
  if (audio.src && !audio.paused) {
    audio.pause();
    return;
  }
  if (audio.src && audio.paused && audio.currentTime > 0) {
    audio.play().catch(() => mostrarEstado("El navegador bloqueó el audio.", "error"));
    return;
  }
  if (audioCache.has(indice)) prepararAudio(audioCache.get(indice));
  else publicarSolicitud(indice);
});

audio.addEventListener("play", () => {
  setIndicador("Leyendo ahora", true);
  mostrarEstado("Puedes leer mientras escuchas. Usa Pausar cuando quieras.");
  actualizarBoton();
  precargarSiguiente();
});

audio.addEventListener("pause", () => {
  if (!audio.ended) setIndicador("Pausado", false);
  actualizarBoton();
});

audio.addEventListener("timeupdate", actualizarPalabraActual);

audio.addEventListener("ended", () => {
  setIndicador("Bloque terminado", false);
  if (palabraActiva >= 0 && palabras[palabraActiva]) palabras[palabraActiva].classList.remove("is-active");
  if (indice < nChunks - 1) {
    indice += 1;
    actualizarNavegacion();
    const siguiente = audioCache.get(indice);
    if (siguiente) prepararAudio(siguiente);
    else publicarSolicitud(indice);
  } else {
    actualizarBoton();
    mostrarEstado("Has terminado el documento.");
  }
});

function moverAChunk(nuevoIndice) {
  indice = nuevoIndice;
  audio.pause();
  audio.removeAttribute("src");
  actualizarNavegacion();
  setIndicador("Listo para leer", false);
  if (audioCache.has(indice)) prepararAudio(audioCache.get(indice));
  else publicarSolicitud(indice);
}

botonAnterior.addEventListener("click", () => {
  if (indice > 0) moverAChunk(indice - 1);
});

botonSiguiente.addEventListener("click", () => {
  if (indice < nChunks - 1) moverAChunk(indice + 1);
});

document.getElementById("archivo").addEventListener("change", (evento) => {
  const archivo = evento.target.files[0];
  if (archivo) subirArchivo(archivo).catch((error) => mostrarEstado(error.message, "error"));
});

cargarVoces();
cargarEstadoTraduccion();
