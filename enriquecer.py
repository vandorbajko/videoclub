#!/usr/bin/env python3
"""Enriquece el listado del videoclub con datos de TMDB.

Uso:
    python3 enriquecer.py [datos/hoja.csv]

Entradas:
    datos/hoja.csv          exportación de la hoja de Google, una fila por copia física:
                            Título, Formato, Notas internas (pistas / uso propio), Notas (públicas)
    datos/correcciones.csv  opcional: titulo,nota_interna,tmdb_id
                            tmdb_id = 123 (película), tv:123 (serie), 123+456 (dos en un disco)
                            o manual (inédita / no está en TMDB);
                            nota_interna vacía = vale para cualquier fila con ese título

Salidas:
    datos/peliculas.json    una ficha por película o serie, con sus copias
    datos/revisar.csv       títulos dudosos o no encontrados, con candidatos
"""
import csv
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

RAIZ = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(RAIZ, "datos")
CACHE = os.path.join(RAIZ, "cache")
API = "https://api.themoviedb.org/3"
RUTA = {"pelicula": "movie", "serie": "tv"}
UMBRAL = 0.85
# Palabras de las notas internas que no sirven para reconocer a nadie en los créditos.
VACIAS = set("""la el lo de del los las con una uno por para que esta este original originales
    edicion ediciones copia copias diferentes primera segunda serie series animacion anmacion
    remake pelicula peliculas version clasico clasica varias compilaciones completa completo
    alquiler anos temporada especial steelbook argentina italiana inglesa alemana pack grandes
    clasicos estuche carton deluxe aniversario mascara metalica remasterizada espacial aventuras""".split())


def leer_token():
    with open(os.path.join(RAIZ, ".env")) as f:
        for linea in f:
            if linea.startswith("TMDB_TOKEN="):
                return linea.split("=", 1)[1].strip()
    sys.exit("Falta TMDB_TOKEN en .env")


TOKEN = leer_token()


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    texto = re.sub(r"[^a-z0-9 ]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def tmdb(ruta, **params):
    """GET a TMDB con caché en disco, para poder relanzar el script sin repetir llamadas."""
    consulta = urllib.parse.urlencode(sorted(params.items()))
    legible = re.sub(r"[^A-Za-z0-9]+", "_", f"{ruta}_{consulta}")[:150]
    huella = hashlib.md5(f"{ruta}?{consulta}".encode()).hexdigest()[:10]
    fichero = os.path.join(CACHE, f"{legible}_{huella}.json")
    if os.path.exists(fichero):
        with open(fichero) as f:
            return json.load(f)
    peticion = urllib.request.Request(
        f"{API}{ruta}?{consulta}",
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"},
    )
    for intento in range(4):
        try:
            with urllib.request.urlopen(peticion, timeout=20) as r:
                datos = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and intento < 3:
                time.sleep(2 * (intento + 1))
                continue
            raise
    os.makedirs(CACHE, exist_ok=True)
    with open(fichero, "w") as f:
        json.dump(datos, f)
    time.sleep(0.03)
    return datos


# ---------------------------------------------------------------- hoja

def formatos(bruto):
    """«Bluray, DVD» → ["Blu-ray", "DVD"]; «Buray» → Blu-ray; «Bluray 4k» → 4K UHD."""
    salida = []
    for parte in re.split(r",|/|\+|\by\b", bruto):
        p = normalizar(parte).replace(" ", "")
        if not p:
            continue
        if "4k" in p or "uhd" in p:
            salida.append("4K UHD")
        elif "3d" in p:
            salida.append("Blu-ray 3D")
        elif p.startswith(("blu", "bur", "br", "bl")):
            salida.append("Blu-ray")
        elif "dvd" in p:
            salida.append("DVD")
        elif "vhs" in p:
            salida.append("VHS")
        elif p in ("digital", "archivo", "archivodigital", "fichero"):
            salida.append("Digital")
        else:
            salida.append(parte.strip())
    return salida or ["¿?"]


def columna(cabecera, *nombres):
    for i, c in enumerate(cabecera):
        if normalizar(c) in nombres:
            return i
    return None


def leer_hoja(ruta):
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        filas = list(csv.reader(f))
    cab = filas[0]
    i_tit = columna(cab, "titulo", "title", "pelicula")
    i_for = columna(cab, "formato", "format", "soporte")
    i_int = columna(cab, "notas internas", "nota interna", "notas privadas")
    i_not = columna(cab, "notas", "nota", "observaciones", "comentarios")
    i_ano = columna(cab, "ano", "anio", "year")
    if i_tit is None:
        sys.exit(f"No encuentro la columna de título en: {cab}")
    val = lambda fila, i: fila[i].strip() if i is not None and i < len(fila) else ""

    salida = []
    for n, fila in enumerate(filas[1:], start=2):
        titulo = re.sub(r"\s+", " ", val(fila, i_tit))
        if not titulo:
            continue
        interna = val(fila, i_int)
        cuantas = re.search(r"\b(\d+)\s+copias\b", normalizar(interna))
        lista = formatos(val(fila, i_for))
        if cuantas and len(lista) == 1:
            lista = lista * int(cuantas.group(1))
        ano = re.search(r"(18|19|20)\d\d", val(fila, i_ano))
        salida.append({
            "fila": n,
            "titulo": titulo,
            "formatos": lista,
            "nota_interna": interna,
            "notas": val(fila, i_not),
            "anio": int(ano.group()) if ano else None,
        })
    return salida


def leer_correcciones():
    ruta = os.path.join(DATOS, "correcciones.csv")
    correcciones = {}
    if os.path.exists(ruta):
        with open(ruta, newline="", encoding="utf-8-sig") as f:
            for c in csv.DictReader(f):
                clave = (normalizar(c["titulo"]), normalizar(c.get("nota_interna")))
                correcciones[clave] = c["tmdb_id"].strip()
    return correcciones


# ---------------------------------------------------------------- pistas de las notas internas

def pistas(titulo, interna, publica=""):
    """Lo que las notas internas cuentan sobre cuál es la buena."""
    t, n = normalizar(titulo), normalizar(interna)
    p = {"anio": None, "rango": None, "orden": None, "palabras": set(), "palabras_publicas": set(),
         "serie": bool(re.search(r"\bserie|temporada|complete series\b", f"{t} {n}"))}
    decada = re.search(r"\blos (\d{2}|\d{4})s?\b", n)
    if decada:
        d = int(decada.group(1))
        d = d + (1900 if d >= 30 else 2000) if d < 100 else d
        p["rango"] = (d, d + 9)
    exacto = re.search(r"\b(19|20)\d\d\b", re.sub(r"\blos (\d{2}|\d{4})s?\b", "", n))
    corto = re.search(r"\b(?:del|de|ano)\s+(\d{2})\b", n)
    if exacto:
        p["anio"] = int(exacto.group())
    elif corto:
        d = int(corto.group(1))
        p["anio"] = d + (1900 if d >= 30 else 2000)
    if "remake" in n:
        p["orden"] = "reciente"
    elif re.search(r"\b(original|primera)\b", n):
        p["orden"] = "antigua"
    utiles = lambda texto: {w for w in normalizar(texto).split()
                            if len(w) >= 4 and w not in VACIAS and not w.isdigit()}
    p["palabras"] = utiles(interna)
    p["palabras_publicas"] = utiles(publica) - p["palabras"]
    return p


# ---------------------------------------------------------------- búsqueda

def variantes(titulo):
    """El título tal cual, sin paréntesis, lo de dentro, sin «3D»/«007»/«temporada», cada lado de «/»."""
    limpio = lambda t: re.sub(r"\s+", " ", t.replace("?", "")).strip(" .-,")
    sin_extra = re.sub(r"\(.*?\)|\b(3D|007)\b|\b(the )?complete series\b|\bserie completa\b"
                       r"|\b(primera|segunda|tercera) temporada\b|\btemporada \d+\b", "", titulo, flags=re.I)
    salida = [titulo, re.sub(r"\(.*?\)", "", titulo), sin_extra]
    salida += re.findall(r"\((.*?)\)", titulo)
    salida += titulo.split(" / ") if " / " in titulo else []
    vistas, unicas = set(), []
    for v in map(limpio, salida):
        if len(v) > 1 and normalizar(v) not in vistas:
            vistas.add(normalizar(v))
            unicas.append(v)
    return unicas


def unificar(c, tipo):
    """Resultados de película y de serie con los mismos nombres de campo."""
    return {
        "id": c["id"], "tipo": tipo,
        "title": c.get("title") or c.get("name"),
        "original_title": c.get("original_title") or c.get("original_name"),
        "release_date": c.get("release_date") or c.get("first_air_date"),
        "vote_count": c.get("vote_count", 0),
        "poster_path": c.get("poster_path"),
    }


def ano_de(c):
    fecha = c.get("release_date") or ""
    return int(fecha[:4]) if fecha[:4].isdigit() else None


NUMEROS = {"uno": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5", "seis": "6", "siete": "7",
           "ocho": "8", "nueve": "9", "diez": "10", "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
           "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10"}


def numeros(texto):
    """{"4"} para «Rocky IV», {"3"} para «Tres solteros»: distingue secuelas."""
    return {NUMEROS.get(w, w) for w in texto.split() if w.isdigit() or w in NUMEROS}


def puntuar(c, consulta, p):
    """0..1: parecido del título (español u original) y encaje con el año de las pistas."""
    t = normalizar(consulta)
    parecido = 0
    for nombre in (normalizar(c.get("title")), normalizar(c.get("original_title"))):
        esta = SequenceMatcher(None, t, nombre).ratio()
        palabras = set(t.split()) - {"y", "and"}
        if len(palabras) >= 2 and palabras <= set(nombre.split()):
            esta = max(esta, 0.88)  # título abreviado en la hoja
        if numeros(t) != numeros(nombre):
            esta *= 0.8  # «Rocky V» no es «Rocky IV»; «Fast & Furious» no es la 7
        parecido = max(parecido, esta)
    ano = ano_de(c)
    if ano and p["anio"]:
        d = abs(ano - p["anio"])
        parecido *= 1.0 if d == 0 else 0.95 if d == 1 else 0.6
    elif ano and p["rango"]:
        parecido *= 1.0 if p["rango"][0] <= ano <= p["rango"][1] else 0.7
    return parecido


def creditos(c):
    """Nombres de reparto, equipo y productoras, para cruzarlos con las notas internas."""
    if c["tipo"] == "serie":
        d = tmdb(f"/tv/{c['id']}", language="es-ES", append_to_response="aggregate_credits")
        gente = d.get("aggregate_credits", {}).get("cast", [])[:20] + d.get("created_by", [])
    else:
        d = tmdb(f"/movie/{c['id']}", language="es-ES", append_to_response="credits")
        cr = d.get("credits", {})
        gente = cr.get("cast", [])[:20] + [x for x in cr.get("crew", [])
                                           if x.get("department") in ("Directing", "Writing")]
    nombres = ([x.get("name", "") for x in gente] + [x["name"] for x in d.get("production_companies", [])]
               + [d.get("title") or d.get("name") or "", d.get("original_title") or d.get("original_name") or ""])
    return set(normalizar(" ".join(nombres)).split())


def coincidencias(palabras, nombres):
    """Cuántas palabras de las notas salen en los créditos, tolerando erratas («Stolz» ~ «Stoltz»)."""
    return sum(1 for w in palabras
               if w in nombres or any(SequenceMatcher(None, w, n).ratio() >= 0.8 for n in nombres))


def buscar(titulo, p):
    """Devuelve (candidato elegido o None, dudosa, candidatos ordenados)."""
    tipos = ["serie", "pelicula"] if p["serie"] else ["pelicula", "serie"]
    puntos, por_clave = {}, {}

    def probar(consulta, tipo, contra=None, peso=1.0):
        params = {"query": consulta, "language": "es-ES"}
        if p["anio"] and tipo == "pelicula":
            con_ano = tmdb("/search/movie", year=p["anio"], **params)["results"]
        else:
            con_ano = []
        resultados = con_ano + tmdb(f"/search/{RUTA[tipo]}", **params)["results"]
        for bruto in resultados[:20]:
            c = unificar(bruto, tipo)
            clave = (tipo, c["id"])
            por_clave.setdefault(clave, c)
            puntos[clave] = max(puntos.get(clave, 0), peso * puntuar(c, contra or consulta, p))

    mejor = lambda: max(puntos.values(), default=0)
    for tipo in tipos:
        for i, consulta in enumerate(variantes(titulo)):
            probar(consulta, tipo, peso=1.0 if i == 0 else 0.97)
        if mejor() >= UMBRAL:
            break
    if mejor() < UMBRAL:
        # Erratas («Cocodrlo Dundee»): buscar quitando una palabra y comparar con el título entero.
        palabras = re.sub(r"\(.*?\)", "", titulo).split()
        if len(palabras) >= 2:
            for i in range(min(len(palabras), 4)):
                probar(" ".join(palabras[:i] + palabras[i + 1:]), tipos[0], contra=titulo)
                if mejor() >= UMBRAL:
                    break

    candidatos = sorted(por_clave.values(), key=lambda c: -puntos[(c["tipo"], c["id"])])
    punto = lambda c: puntos[(c["tipo"], c["id"])]
    if not candidatos or punto(candidatos[0]) < UMBRAL:
        return None, False, candidatos[:5]

    # Empates (remakes, secuelas, mismo título): decide lo que digan las notas internas y,
    # si no dicen nada, la más conocida. Si la segunda también es conocida, queda dudosa.
    margen = 0.02 if punto(candidatos[0]) >= 0.99 else 0.1
    empatados = [c for c in candidatos if punto(candidatos[0]) - punto(c) < margen]
    resuelta = sospechosa = False
    palabras = p["palabras"] | p["palabras_publicas"]
    if palabras:
        buenas = [c for c in candidatos[:8] if punto(c) >= UMBRAL]
        aciertos = {id(c): coincidencias(palabras, creditos(c)) for c in buenas}
        maximo = max(aciertos.values(), default=0)
        if maximo:
            empatados = [c for c in buenas if aciertos[id(c)] == maximo]
            resuelta = len(empatados) == 1
        elif p["palabras"]:
            sospechosa = True  # las notas internas nombran a alguien que no sale en ninguna
    if len(empatados) > 1 and p["orden"]:
        votos = max(c["vote_count"] for c in empatados)
        conocidas = [c for c in empatados if ano_de(c) and c["vote_count"] >= 0.2 * votos]
        if conocidas:
            elegida = (min if p["orden"] == "antigua" else max)(conocidas, key=ano_de)
            empatados, resuelta = [elegida], True
    if len(empatados) > 1 and (p["anio"] or p["rango"]):
        resuelta = True  # el año ya ha pesado en la puntuación
    empatados.sort(key=lambda c: -c["vote_count"])
    elegida = empatados[0]
    dudosa = sospechosa or (not resuelta and any(
        c["vote_count"] >= 0.2 * max(elegida["vote_count"], 1) for c in empatados[1:]))
    candidatos.remove(elegida)
    return elegida, dudosa, [elegida] + candidatos[:4]


PACK = re.compile(r"\b(trilogia|tetralogia|quadrilogy|quadrilogia|trilogy|saga|coleccion|pack|integral)\b")
CUANTAS = {"trilogia": 3, "trilogy": 3, "tetralogia": 4, "quadrilogy": 4, "quadrilogia": 4}


def buscar_pack(titulo):
    """«La Trilogía de Bourne» → las 3 primeras películas estrenadas de la colección Bourne."""
    t = normalizar(titulo)
    palabra = PACK.search(t).group(1)
    consulta = re.sub(r"\b(la|el|los|las|de|del|original|edicion|especial)\b", " ", PACK.sub(" ", t))
    consulta = re.sub(r"\s+", " ", consulta).strip()
    # En español la saga original se llama «La guerra de las galaxias»: buscar también en inglés.
    colecciones = (tmdb("/search/collection", query=consulta, language="es-ES")["results"]
                   + tmdb("/search/collection", query=consulta, language="en-US")["results"])
    if not colecciones:
        return None, []
    nombre = lambda c: re.sub(r"\b(coleccion|collection)\b", "", normalizar(c["name"])).strip()
    mejor = max(colecciones, key=lambda c: SequenceMatcher(None, consulta, nombre(c)).ratio())
    col = tmdb(f"/collection/{mejor['id']}", language="es-ES")
    partes = sorted((p for p in col.get("parts", []) if p.get("release_date")),
                    key=lambda p: p["release_date"])
    return col.get("name"), [p["id"] for p in partes[:CUANTAS.get(palabra, len(partes))]]


# ---------------------------------------------------------------- fichas

def resumir(candidatos):
    """Lo justo para que la aplicación ofrezca las alternativas al revisar."""
    return [{"tipo": c["tipo"], "tmdb_id": c["id"], "titulo": c.get("title"), "anio": ano_de(c),
             "caratula": f"https://image.tmdb.org/t/p/w185{c['poster_path']}" if c.get("poster_path") else None}
            for c in candidatos]


def ficha(tipo, tmdb_id):
    unicos = lambda xs: list(dict.fromkeys(xs))
    if tipo == "serie":
        d = tmdb(f"/tv/{tmdb_id}", language="es-ES", append_to_response="aggregate_credits")
        sinopsis = d.get("overview") or tmdb(f"/tv/{tmdb_id}", language="en-US").get("overview")
        fecha = d.get("first_air_date") or ""
        return {
            "tipo": "serie", "tmdb_id": d["id"], "titulo": d.get("name"),
            "titulo_original": d.get("original_name"),
            "anio": int(fecha[:4]) if fecha[:4].isdigit() else None,
            "duracion": (d.get("episode_run_time") or [None])[0],
            "generos": [g["name"] for g in d.get("genres", [])],
            "director": unicos(p["name"] for p in d.get("created_by", [])),
            "guion": [],
            "reparto": [p["name"] for p in d.get("aggregate_credits", {}).get("cast", [])[:8]],
            "sinopsis": sinopsis,
            "caratula": f"https://image.tmdb.org/t/p/w500{d['poster_path']}" if d.get("poster_path") else None,
        }
    d = tmdb(f"/movie/{tmdb_id}", language="es-ES", append_to_response="credits")
    sinopsis = d.get("overview") or tmdb(f"/movie/{tmdb_id}", language="en-US").get("overview")
    equipo = d.get("credits", {}).get("crew", [])
    return {
        "tipo": "pelicula", "tmdb_id": d["id"], "titulo": d.get("title"),
        "titulo_original": d.get("original_title"),
        "anio": int(d["release_date"][:4]) if d.get("release_date") else None,
        "duracion": d.get("runtime") or None,
        "generos": [g["name"] for g in d.get("genres", [])],
        "director": unicos(p["name"] for p in equipo if p.get("job") == "Director"),
        "guion": unicos(p["name"] for p in equipo if p.get("department") == "Writing")[:4],
        "reparto": [p["name"] for p in d.get("credits", {}).get("cast", [])[:8]],
        "sinopsis": sinopsis,
        "caratula": f"https://image.tmdb.org/t/p/w500{d['poster_path']}" if d.get("poster_path") else None,
    }


# ---------------------------------------------------------------- principal

def main():
    hoja = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DATOS, "hoja.csv")
    filas = leer_hoja(hoja)
    correcciones = leer_correcciones()

    # Filas con el mismo título y las mismas notas internas son la misma película.
    grupos = {}
    for f in filas:
        grupos.setdefault((normalizar(f["titulo"]), normalizar(f["nota_interna"])), []).append(f)

    peliculas, por_clave, revisar = [], {}, []

    def anadir(tipo, tmdb_id, copias, dudosa=False, candidatos=()):
        clave = (tipo, tmdb_id)
        if clave not in por_clave:
            p = ficha(tipo, tmdb_id)
            p.update(copias=[], estado="ok", candidatos=[])
            por_clave[clave] = p
            peliculas.append(p)
        p = por_clave[clave]
        p["copias"].extend(copias)
        if dudosa:
            p["estado"] = "comprobar"
            p["candidatos"] = resumir(candidatos)
        return p

    for n, ((clave_t, clave_n), grupo) in enumerate(grupos.items(), start=1):
        titulo, interna = grupo[0]["titulo"], grupo[0]["nota_interna"]
        copias = [{"formato": fmt, "notas": f["notas"], "nota_interna": f["nota_interna"],
                   "titulo_hoja": f["titulo"]} for f in grupo for fmt in f["formatos"]]
        filas_txt = " ".join(str(f["fila"]) for f in grupo)
        print(f"[{n}/{len(grupos)}] {titulo}" + (f"  ({interna})" if interna else ""), end="  ", flush=True)

        forzado = correcciones.get((clave_t, clave_n)) or correcciones.get((clave_t, ""))
        texto_notas = normalizar(" ".join(f["nota_interna"] + " " + f["notas"] for f in grupo))
        if forzado == "manual" or "inedit" in texto_notas:
            print("→ ficha manual")
            peliculas.append({"tipo": "pelicula", "tmdb_id": None, "titulo": titulo,
                              "anio": grupo[0]["anio"], "estado": "manual", "copias": copias})
            continue

        if forzado:  # «123», «tv:123» o varias en un mismo disco: «123+456»
            nombres = []
            for parte in forzado.split("+"):
                tipo, _, ident = parte.strip().rpartition(":")
                p = anadir("serie" if tipo == "tv" else "pelicula", int(ident), copias)
                nombres.append(f"{p['titulo']} ({p['anio']})")
            print(f"→ {', '.join(nombres)} [corrección]")
            continue

        if "ilegible" in clave_t:
            print("→ ILEGIBLE")
            revisar.append({"estado": "ilegible", "titulo": titulo, "nota_interna": interna,
                            "filas": filas_txt, "candidatos": ""})
            peliculas.append({"tipo": "pelicula", "tmdb_id": None, "titulo": titulo, "anio": None,
                              "estado": "pendiente", "copias": copias})
            continue

        if PACK.search(clave_t):
            nombre, ids = buscar_pack(titulo)
            if ids:
                nota = f"Pack: {titulo}"
                for tmdb_id in ids:
                    anadir("pelicula", tmdb_id, [dict(c, notas="; ".join(x for x in (nota, c["notas"]) if x))
                                                 for c in copias])
                print(f"→ pack «{nombre}»: " + ", ".join(por_clave[("pelicula", i)]["titulo"] for i in ids))
                continue

        p_hoja = pistas(titulo, interna, " ".join(f["notas"] for f in grupo))
        if grupo[0]["anio"]:
            p_hoja["anio"] = grupo[0]["anio"]
        elegida, dudosa, candidatos = buscar(titulo, p_hoja)
        if not elegida or dudosa:
            print("→ DUDOSA" if dudosa else "→ SIN ELEGIR", end="  " if dudosa else "\n")
            revisar.append({
                "estado": "comprobar" if dudosa else "sin elegir",
                "titulo": titulo, "nota_interna": interna, "filas": filas_txt,
                "candidatos": " | ".join(
                    f"{'tv:' if c['tipo'] == 'serie' else ''}{c['id']}: {c.get('title')} ({ano_de(c) or '????'})"
                    for c in candidatos) or "sin resultados",
            })
        if not elegida:
            peliculas.append({"tipo": "pelicula", "tmdb_id": None, "titulo": titulo, "anio": None,
                              "estado": "pendiente", "candidatos": resumir(candidatos), "copias": copias})
            continue

        repetida = (elegida["tipo"], elegida["id"]) in por_clave
        p = anadir(elegida["tipo"], elegida["id"], copias, dudosa, candidatos)
        etiqueta = " [serie]" if p["tipo"] == "serie" else ""
        print(f"→ se suma a «{p['titulo']}»" if repetida else f"→ {p['titulo']} ({p['anio']}){etiqueta}")

    with open(os.path.join(DATOS, "peliculas.json"), "w", encoding="utf-8") as f:
        json.dump(peliculas, f, ensure_ascii=False, indent=1)
    with open(os.path.join(DATOS, "revisar.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["estado", "titulo", "nota_interna", "filas", "candidatos"])
        w.writeheader()
        w.writerows(revisar)

    cuenta = lambda e: sum(1 for p in peliculas if p.get("estado") == e)
    print(f"\n{sum(len(f['formatos']) for f in filas)} copias → {len(peliculas)} fichas "
          f"({sum(1 for p in peliculas if p.get('tipo') == 'serie')} series): "
          f"{cuenta('ok')} ok, {cuenta('comprobar')} dudosas, {cuenta('pendiente')} sin elegir, "
          f"{cuenta('manual')} manuales.")


if __name__ == "__main__":
    main()
