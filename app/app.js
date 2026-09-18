import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm";
import { SUPABASE_URL, SUPABASE_KEY } from "./config.js";

const db = createClient(SUPABASE_URL, SUPABASE_KEY);
const FORMATOS = ["VHS", "DVD", "Blu-ray", "Blu-ray 3D", "4K UHD", "Digital"];
const CHIPS = ["VHS", "DVD", "Blu-ray", "4K UHD", "Digital"];
const CLAVE_CACHE = "videoclub.peliculas.v1";
const CLAVE_FORMATO = "videoclub.ultimo-formato";

const estado = {
  peliculas: [],
  sesion: null,
  texto: "",
  formato: "",
  genero: "",
  orden: "titulo",
  revisar: false,
};

const $ = (s, raiz = document) => raiz.querySelector(s);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const normalizar = (t) => (t || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "")
  .toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const guardarLocal = (clave, valor) => { try { localStorage.setItem(clave, valor); } catch {} };
const leerLocal = (clave) => { try { return localStorage.getItem(clave); } catch { return null; } };

/* ================= Datos ================= */

function preparar(p) {
  p.copias ??= [];
  p.generos ??= [];
  p.director ??= [];
  p.guion ??= [];
  p.reparto ??= [];
  p._b = normalizar([p.titulo, p.titulo_original, p.anio, ...p.director, ...p.reparto,
    ...p.copias.map((c) => c.titulo_hoja)].join(" "));
  return p;
}

function guardarCache() {
  const limpias = estado.peliculas.map(({ _b, ...p }) => p);
  guardarLocal(CLAVE_CACHE, JSON.stringify(limpias));
}

async function cargar() {
  const guardado = leerLocal(CLAVE_CACHE);
  if (guardado) {
    try {
      estado.peliculas = JSON.parse(guardado).map(preparar);
      pintar();
    } catch {}
  }
  try {
    const todas = [];
    for (let desde = 0; ; desde += 1000) {
      const { data, error } = await db.from("peliculas").select("*").order("id").range(desde, desde + 999);
      if (error) throw error;
      todas.push(...data);
      if (data.length < 1000) break;
    }
    estado.peliculas = todas.map(preparar);
    guardarCache();
    $("#estado-red").textContent = "";
  } catch (e) {
    console.error(e);
    $("#estado-red").textContent = estado.peliculas.length
      ? "Sin conexión: catálogo guardado en el móvil"
      : "No se pudo cargar el catálogo";
  }
  pintar();
}

function sustituir(fila) {
  const p = preparar(fila);
  const i = estado.peliculas.findIndex((x) => x.id === p.id);
  if (i >= 0) estado.peliculas[i] = p;
  else estado.peliculas.push(p);
  guardarCache();
  pintar();
  return p;
}

function quitar(id) {
  estado.peliculas = estado.peliculas.filter((p) => p.id !== id);
  guardarCache();
  pintar();
}

async function actualizar(p, cambios) {
  const { data, error } = await db.from("peliculas").update(cambios).eq("id", p.id).select().single();
  if (error) throw error;
  return sustituir(data);
}

/* ================= TMDB (solo con sesión: la clave vive en la tabla ajustes) ================= */

let tokenTmdb = null;

async function tmdb(ruta, params = {}) {
  if (!tokenTmdb) {
    const { data, error } = await db.from("ajustes").select("valor").eq("clave", "tmdb_token").maybeSingle();
    if (error || !data) throw new Error("Falta la clave de TMDB en la tabla ajustes.");
    tokenTmdb = data.valor;
  }
  const url = new URL("https://api.themoviedb.org/3" + ruta);
  for (const [k, v] of Object.entries({ language: "es-ES", ...params })) url.searchParams.set(k, v);
  const r = await fetch(url, { headers: { Authorization: `Bearer ${tokenTmdb}` } });
  if (!r.ok) throw new Error(`TMDB respondió ${r.status}`);
  return r.json();
}

const unicos = (xs) => [...new Set(xs)];

async function fichaTmdb(id) {
  const d = await tmdb(`/movie/${id}`, { append_to_response: "credits" });
  let sinopsis = d.overview;
  if (!sinopsis) sinopsis = (await tmdb(`/movie/${id}`, { language: "en-US" })).overview;
  const equipo = d.credits?.crew ?? [];
  return {
    tmdb_id: d.id,
    titulo: d.title,
    titulo_original: d.original_title,
    anio: d.release_date ? Number(d.release_date.slice(0, 4)) : null,
    duracion: d.runtime || null,
    generos: (d.genres ?? []).map((g) => g.name),
    director: unicos(equipo.filter((p) => p.job === "Director").map((p) => p.name)),
    guion: unicos(equipo.filter((p) => p.department === "Writing").map((p) => p.name)).slice(0, 4),
    reparto: (d.credits?.cast ?? []).slice(0, 8).map((p) => p.name),
    sinopsis: sinopsis || null,
    caratula: d.poster_path ? `https://image.tmdb.org/t/p/w500${d.poster_path}` : null,
  };
}

async function buscarTmdb(texto) {
  const { results } = await tmdb("/search/movie", { query: texto });
  return results.slice(0, 12).map((c) => ({
    tmdb_id: c.id,
    titulo: c.title,
    titulo_original: c.original_title,
    anio: c.release_date ? Number(c.release_date.slice(0, 4)) : null,
    caratula: c.poster_path ? `https://image.tmdb.org/t/p/w185${c.poster_path}` : null,
  }));
}

/* ================= Listado ================= */

function filtradas() {
  const palabras = normalizar(estado.texto).split(" ").filter(Boolean);
  const lista = estado.peliculas.filter((p) =>
    (!estado.revisar || p.estado === "comprobar" || p.estado === "pendiente") &&
    (!estado.formato || p.copias.some((c) => (c.formato || "").startsWith(estado.formato))) &&
    (!estado.genero || p.generos.includes(estado.genero)) &&
    palabras.every((w) => p._b.includes(w)));
  const porTitulo = (a, b) => a.titulo.localeCompare(b.titulo, "es", { sensitivity: "base" });
  const orden = {
    titulo: porTitulo,
    anio: (a, b) => (a.anio ?? 9999) - (b.anio ?? 9999) || porTitulo(a, b),
    "anio-desc": (a, b) => (b.anio ?? 0) - (a.anio ?? 0) || porTitulo(a, b),
    creada: (a, b) => (b.creada || "").localeCompare(a.creada || "") || b.id - a.id,
  }[estado.orden];
  return lista.sort(orden);
}

const porRevisar = () => estado.peliculas.filter((p) => p.estado === "comprobar" || p.estado === "pendiente").length;

function etiquetas(copias) {
  return copias.map((c) => `<span class="formato" data-f="${esc(c.formato)}">${esc(c.formato || "¿?")}</span>`).join("");
}

function cartel(p, ancho = "w342") {
  const revisar = p.estado === "comprobar" || p.estado === "pendiente";
  return `<div class="cartel">
    ${p.caratula
      ? `<img loading="lazy" alt="" src="${esc(p.caratula.replace("/w500/", `/${ancho}/`))}">`
      : `<div class="sin-imagen">${esc(p.titulo)}</div>`}
    ${revisar && estado.sesion ? `<span class="marca-revisar" title="Por revisar">?</span>` : ""}
  </div>`;
}

function pintarFiltros() {
  const chips = [["", "Todo"], ...CHIPS.map((f) => [f, f])].map(([valor, texto]) =>
    `<button type="button" class="chip" data-formato="${esc(valor)}"
       aria-pressed="${!estado.revisar && estado.formato === valor}">${esc(texto)}</button>`);
  const n = porRevisar();
  if (estado.sesion && n) {
    chips.push(`<button type="button" class="chip revisar" data-revisar aria-pressed="${estado.revisar}">
      Por revisar (${n})</button>`);
  }
  $("#filtros").innerHTML = chips.join("");

  const generos = unicos(estado.peliculas.flatMap((p) => p.generos)).sort((a, b) => a.localeCompare(b, "es"));
  const select = $("#genero");
  select.innerHTML = `<option value="">Todos los géneros</option>` +
    generos.map((g) => `<option ${g === estado.genero ? "selected" : ""}>${esc(g)}</option>`).join("");
}

function pintar() {
  const lista = filtradas();
  const copias = estado.peliculas.reduce((n, p) => n + p.copias.length, 0);
  $("#recuento").textContent = estado.peliculas.length
    ? `${estado.peliculas.length} películas · ${copias} copias` : "";
  pintarFiltros();

  $("#rejilla").innerHTML = lista.map((p) => `
    <button type="button" class="tarjeta" data-id="${p.id}">
      ${cartel(p)}
      <div class="titulo">${esc(p.titulo)}</div>
      <div class="meta">${p.anio ? `<span>${p.anio}</span>` : ""}${etiquetas(p.copias)}</div>
    </button>`).join("");

  const vacio = $("#vacio");
  vacio.hidden = lista.length > 0 || !estado.peliculas.length;
  if (!vacio.hidden) {
    const texto = estado.texto.trim();
    vacio.innerHTML = texto
      ? `<strong>No la tenemos</strong>No hay nada que coincida con «${esc(texto)}»${
          estado.formato || estado.genero || estado.revisar ? " con los filtros elegidos" : ""}.
         ${estado.sesion ? `<div class="acciones" style="justify-content:center">
           <button type="button" class="primario" data-anadir-busqueda>Añadir «${esc(texto)}»</button></div>` : ""}`
      : `<strong>Nada por aquí</strong>Ninguna película con estos filtros.`;
  }

  const aviso = $("#aviso");
  aviso.hidden = !estado.revisar;
  aviso.textContent = "Películas dudosas (hay varias con el mismo título) o sin ficha. Ábrelas para confirmar o corregir.";
}

/* ================= Hojas (diálogos) y botón atrás de Android ================= */

function abrir(dialogo) {
  if (dialogo.open) return;
  dialogo.showModal();
  if (!history.state?.hoja) history.pushState({ hoja: true }, "");
}

for (const d of document.querySelectorAll("dialog")) {
  d.addEventListener("click", (e) => {
    if (e.target === d || e.target.closest("[data-cerrar]")) d.close();
  });
  d.addEventListener("close", () => {
    if (!document.querySelector("dialog[open]") && history.state?.hoja) history.back();
  });
}
addEventListener("popstate", () => {
  for (const d of document.querySelectorAll("dialog[open]")) d.close();
});

/* ================= Ficha ================= */

const lista = (titulo, xs) => xs?.length ? `<h3>${titulo}</h3><p class="personas">${xs.map(esc).join(", ")}</p>` : "";

function opcionesFormato(elegido) {
  return FORMATOS.map((f) => `<option ${f === elegido ? "selected" : ""}>${f}</option>`).join("");
}

function resultadosHtml(resultados, excluir) {
  const tengo = new Set(estado.peliculas.map((p) => p.tmdb_id));
  return resultados.filter((r) => r.tmdb_id !== excluir).map((r) => `
    <button type="button" class="resultado" data-tmdb="${r.tmdb_id}">
      ${r.caratula ? `<img loading="lazy" alt="" src="${esc(r.caratula)}">` : `<span class="hueco"></span>`}
      <span><strong>${esc(r.titulo)}</strong> ${r.anio ? `(${r.anio})` : ""}
        ${r.titulo_original && r.titulo_original !== r.titulo ? `<br><span class="nota-pequena">${esc(r.titulo_original)}</span>` : ""}
        ${tengo.has(r.tmdb_id) ? `<br><span class="ya">Ya la tienes</span>` : ""}</span>
    </button>`).join("") || `<p class="nota-pequena">Sin resultados.</p>`;
}

function abrirFicha(p) {
  const d = $("#ficha");
  const admin = !!estado.sesion;
  const dudosa = p.estado === "comprobar" || p.estado === "pendiente";
  const duracion = p.duracion ? `${Math.floor(p.duracion / 60)} h ${p.duracion % 60} min` : "";

  d.innerHTML = `
    <button type="button" class="cerrar" data-cerrar aria-label="Cerrar">×</button>
    <div class="contenido">
      <div class="cabeza-ficha">
        ${cartel(p, "w342")}
        <div class="datos">
          <h2>${esc(p.titulo)}</h2>
          ${p.titulo_original && p.titulo_original !== p.titulo ? `<p class="original">${esc(p.titulo_original)}</p>` : ""}
          <p class="linea">${[p.anio, duracion].filter(Boolean).join(" · ")}</p>
          <p class="linea">${esc(p.generos.join(", "))}</p>
          <div class="meta" style="margin-top:8px">${etiquetas(p.copias)}</div>
        </div>
      </div>

      ${admin && dudosa ? `<div class="caja-aviso">
          <p>${p.estado === "pendiente"
            ? "Esta película no tiene ficha todavía. Elige cuál es:"
            : "Hay varias películas con este título. ¿Es esta la tuya?"}</p>
          ${p.tmdb_id ? `<button type="button" class="primario mini" data-correcta>Sí, es esta</button>` : ""}
          <div class="resultados">${resultadosHtml(p.candidatos ?? [], p.tmdb_id)}</div>
        </div>` : ""}

      ${p.sinopsis ? `<p class="sinopsis">${esc(p.sinopsis)}</p>` : ""}
      ${lista("Dirección", p.director)}
      ${lista("Guion", p.guion)}
      ${lista("Reparto", p.reparto)}

      <h3>Copias</h3>
      <ul class="copias">${p.copias.map((c, i) => `
        <li><span class="formato" data-f="${esc(c.formato)}">${esc(c.formato || "¿?")}</span>
          <span class="notas">${esc(c.notas || "")}${
            c.titulo_hoja && normalizar(c.titulo_hoja) !== normalizar(p.titulo)
              ? `${c.notas ? " · " : ""}«${esc(c.titulo_hoja)}»` : ""}</span>
          ${admin ? `<button type="button" class="peligro mini" data-quitar-copia="${i}">Quitar</button>` : ""}
        </li>`).join("")}</ul>

      ${admin ? `
        <div class="fila-copia" style="margin-top:10px">
          <select id="nueva-copia-formato" aria-label="Formato">${opcionesFormato(leerLocal(CLAVE_FORMATO) || "DVD")}</select>
          <input id="nueva-copia-notas" placeholder="Notas (edición, ubicación…)" style="margin:0">
        </div>
        <div class="acciones" style="margin-top:8px">
          <button type="button" class="secundario mini" data-anadir-copia>Añadir copia</button>
        </div>

        <h3>Corregir</h3>
        <div class="fila-copia">
          <input id="corregir-texto" type="search" placeholder="Buscar la película correcta" value="${esc(p.titulo)}" style="margin:0">
          <button type="button" class="secundario mini" data-corregir-buscar>Buscar</button>
        </div>
        <div class="resultados" id="corregir-resultados"></div>
        <div class="acciones">
          <button type="button" class="peligro" data-eliminar>Eliminar película</button>
        </div>
        <p class="error" id="error-ficha"></p>` : ""}
    </div>`;

  d.onclick = async (e) => {
    const b = e.target.closest("button");
    if (!b || b.hasAttribute("data-cerrar")) return;
    const error = $("#error-ficha", d);
    try {
      b.disabled = true;
      if (b.hasAttribute("data-correcta")) {
        abrirFicha(await actualizar(p, { estado: "ok", candidatos: [] }));
      } else if (b.dataset.tmdb) {
        await cambiarPelicula(p, Number(b.dataset.tmdb));
      } else if (b.hasAttribute("data-quitar-copia")) {
        if (p.copias.length === 1) {
          if (confirm(`Es la única copia. ¿Eliminar «${p.titulo}» del videoclub?`)) await eliminar(p);
        } else if (confirm("¿Quitar esta copia?")) {
          const copias = p.copias.filter((_, i) => i !== Number(b.dataset.quitarCopia));
          abrirFicha(await actualizar(p, { copias }));
        }
      } else if (b.hasAttribute("data-anadir-copia")) {
        const formato = $("#nueva-copia-formato", d).value;
        guardarLocal(CLAVE_FORMATO, formato);
        const copias = [...p.copias, { formato, notas: $("#nueva-copia-notas", d).value.trim() }];
        abrirFicha(await actualizar(p, { copias }));
      } else if (b.hasAttribute("data-corregir-buscar")) {
        $("#corregir-resultados", d).innerHTML = resultadosHtml(await buscarTmdb($("#corregir-texto", d).value), p.tmdb_id);
      } else if (b.hasAttribute("data-eliminar")) {
        if (confirm(`¿Eliminar «${p.titulo}» y todas sus copias?`)) await eliminar(p);
      }
    } catch (err) {
      console.error(err);
      if (error) error.textContent = err.message || "No se pudo guardar.";
    } finally {
      b.disabled = false;
    }
  };
  $("#corregir-texto", d)?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("[data-corregir-buscar]", d).click();
  });

  if (!d.open) d.scrollTop = 0;  // al volver a pintar tras editar, no saltar arriba
  abrir(d);
}

async function eliminar(p) {
  const { error } = await db.from("peliculas").delete().eq("id", p.id);
  if (error) throw error;
  quitar(p.id);
  $("#ficha").close();
}

/** La ficha era otra película: rellenarla con la elegida, o fusionar copias si ya la teníamos. */
async function cambiarPelicula(p, tmdbId) {
  const existente = estado.peliculas.find((x) => x.tmdb_id === tmdbId && x.id !== p.id);
  if (existente) {
    const fusionada = await actualizar(existente, { copias: [...existente.copias, ...p.copias] });
    await db.from("peliculas").delete().eq("id", p.id);
    quitar(p.id);
    abrirFicha(fusionada);
    return;
  }
  const ficha = await fichaTmdb(tmdbId);
  abrirFicha(await actualizar(p, { ...ficha, estado: "ok", candidatos: [] }));
}

/* ================= Alta ================= */

function abrirAlta(textoInicial = "") {
  const d = $("#alta");
  d.innerHTML = `
    <button type="button" class="cerrar" data-cerrar aria-label="Cerrar">×</button>
    <div class="contenido">
      <h2>Añadir película</h2>
      <div class="fila-copia" style="margin-top:12px">
        <input id="alta-texto" type="search" placeholder="Título" value="${esc(textoInicial)}" style="margin:0" enterkeyhint="search">
        <button type="button" class="primario mini" data-alta-buscar>Buscar</button>
      </div>
      <div class="resultados" id="alta-resultados"></div>
      <div class="acciones"><button type="button" class="enlace" data-alta-manual>No está en la lista: añadirla a mano</button></div>
      <p class="error" id="error-alta"></p>
    </div>`;

  const buscar = async () => {
    const texto = $("#alta-texto", d).value.trim();
    if (!texto) return;
    const caja = $("#alta-resultados", d);
    caja.innerHTML = `<p class="nota-pequena">Buscando…</p>`;
    try {
      caja.innerHTML = resultadosHtml(await buscarTmdb(texto));
    } catch (err) {
      caja.innerHTML = "";
      $("#error-alta", d).textContent = err.message;
    }
  };

  d.onclick = (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.hasAttribute("data-alta-buscar")) buscar();
    else if (b.dataset.tmdb) elegirAlta(Number(b.dataset.tmdb), b.querySelector("strong").textContent);
    else if (b.hasAttribute("data-alta-manual")) altaManual($("#alta-texto", d).value.trim());
  };
  $("#alta-texto", d).addEventListener("keydown", (e) => { if (e.key === "Enter") buscar(); });

  abrir(d);
  if (textoInicial) buscar();
  else $("#alta-texto", d).focus();
}

function formularioCopia() {
  return `
    <label>Formato <select name="formato">${opcionesFormato(leerLocal(CLAVE_FORMATO) || "DVD")}</select></label>
    <label>Notas <input name="notas" placeholder="Edición especial, estantería…"></label>`;
}

function elegirAlta(tmdbId, titulo) {
  const d = $("#alta");
  const existente = estado.peliculas.find((p) => p.tmdb_id === tmdbId);
  $(".contenido", d).innerHTML = `
    <form id="form-alta">
      <h2>${esc(titulo)}</h2>
      ${existente ? `<div class="caja-aviso"><p><strong>Ya la tienes</strong> en ${
        existente.copias.map((c) => esc(c.formato)).join(", ") || "—"}.</p>
        <p class="nota-pequena">Si guardas, se añade como otra copia.</p></div>` : ""}
      ${formularioCopia()}
      <p class="error" id="error-alta"></p>
      <div class="acciones">
        <button type="button" class="secundario" data-cerrar>Cancelar</button>
        <button type="submit" class="primario">${existente ? "Añadir copia" : "Guardar"}</button>
      </div>
    </form>`;

  $("#form-alta", d).onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const copia = { formato: f.get("formato"), notas: f.get("notas").trim() };
    guardarLocal(CLAVE_FORMATO, copia.formato);
    const boton = $("button[type=submit]", d);
    boton.disabled = true;
    try {
      let p;
      if (existente) {
        p = await actualizar(existente, { copias: [...existente.copias, copia] });
      } else {
        const ficha = await fichaTmdb(tmdbId);
        const { data, error } = await db.from("peliculas")
          .insert({ ...ficha, copias: [copia], estado: "ok" }).select().single();
        if (error) throw error;
        p = sustituir(data);
      }
      terminarAlta(p);
    } catch (err) {
      console.error(err);
      $("#error-alta", d).textContent = err.message || "No se pudo guardar.";
      boton.disabled = false;
    }
  };
}

function altaManual(titulo) {
  const d = $("#alta");
  $(".contenido", d).innerHTML = `
    <form id="form-manual">
      <h2>Película inédita</h2>
      <p class="nota-pequena">Para lo que no está en TMDB: producciones propias, grabaciones, copias sin editar…</p>
      <label>Título <input name="titulo" required value="${esc(titulo)}"></label>
      <label>Año <input name="anio" type="number" inputmode="numeric" min="1880" max="2100"></label>
      <label>Dirección <input name="director" placeholder="Separa varios nombres con comas"></label>
      <label>Sinopsis <textarea name="sinopsis"></textarea></label>
      ${formularioCopia()}
      <p class="error" id="error-alta"></p>
      <div class="acciones">
        <button type="button" class="secundario" data-cerrar>Cancelar</button>
        <button type="submit" class="primario">Guardar</button>
      </div>
    </form>`;

  $("#form-manual", d).onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const lista = (t) => t.split(",").map((x) => x.trim()).filter(Boolean);
    const fila = {
      titulo: f.get("titulo").trim(),
      anio: f.get("anio") ? Number(f.get("anio")) : null,
      director: lista(f.get("director")),
      sinopsis: f.get("sinopsis").trim() || null,
      copias: [{ formato: f.get("formato"), notas: f.get("notas").trim() }],
      estado: "manual",
    };
    guardarLocal(CLAVE_FORMATO, fila.copias[0].formato);
    try {
      const { data, error } = await db.from("peliculas").insert(fila).select().single();
      if (error) throw error;
      terminarAlta(sustituir(data));
    } catch (err) {
      $("#error-alta", d).textContent = err.message || "No se pudo guardar.";
    }
  };
}

function terminarAlta(p) {
  abrirFicha(p);        // primero abrir la ficha y luego cerrar el alta: así el
  $("#alta").close();   // historial (botón atrás) no cierra también la ficha
}

/* ================= Sesión ================= */

function pintarSesion() {
  $("#boton-sesion").textContent = estado.sesion ? "Salir" : "Entrar";
  $("#boton-anadir").hidden = !estado.sesion;
  if (!estado.sesion) estado.revisar = false;
  pintar();
}

$("#boton-sesion").onclick = async () => {
  if (estado.sesion) {
    await db.auth.signOut();
  } else {
    $("#error-entrar").textContent = "";
    abrir($("#entrar"));
  }
};

$("#form-entrar").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const { error } = await db.auth.signInWithPassword({ email: f.get("email"), password: f.get("password") });
  if (error) {
    $("#error-entrar").textContent = "Correo o contraseña incorrectos.";
    return;
  }
  e.target.reset();
  $("#entrar").close();
};

db.auth.onAuthStateChange((_evento, sesion) => {
  estado.sesion = sesion;
  tokenTmdb = null;
  pintarSesion();
});

/* ================= Eventos del listado ================= */

$("#busqueda").addEventListener("input", (e) => { estado.texto = e.target.value; pintar(); });
$("#genero").addEventListener("change", (e) => { estado.genero = e.target.value; pintar(); });
$("#orden").addEventListener("change", (e) => { estado.orden = e.target.value; pintar(); });

$("#filtros").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  if (chip.hasAttribute("data-revisar")) {
    estado.revisar = !estado.revisar;
    estado.formato = "";
  } else {
    estado.revisar = false;
    estado.formato = chip.dataset.formato;
  }
  pintar();
});

$("#rejilla").addEventListener("click", (e) => {
  const t = e.target.closest(".tarjeta");
  if (t) abrirFicha(estado.peliculas.find((p) => p.id === Number(t.dataset.id)));
});

$("#vacio").addEventListener("click", (e) => {
  if (e.target.closest("[data-anadir-busqueda]")) abrirAlta(estado.texto.trim());
});

$("#boton-anadir").onclick = () => abrirAlta();

/* ================= Arranque ================= */

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
cargar();
