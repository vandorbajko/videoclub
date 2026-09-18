#!/usr/bin/env python3
"""Enriquece el listado de películas (Título, Formato, Año, Notas) con datos de TMDB.

Uso:
    python3 enriquecer.py datos/hoja.csv

Entradas:
    datos/hoja.csv          exportación de la hoja de Google (una fila por copia física)
    datos/correcciones.csv  opcional: titulo,anio,tmdb_id  (tmdb_id = "manual" para inéditas)

Salidas:
    datos/peliculas.json    una ficha por película, con sus copias
    datos/revisar.csv       títulos dudosos o no encontrados, con candidatos
"""
import csv
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

RAIZ = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(RAIZ, "datos")
CACHE = os.path.join(RAIZ, "cache")
API = "https://api.themoviedb.org/3"
FORMATOS = {
    "vhs": "VHS", "dvd": "DVD", "bluray": "Blu-ray", "blu ray": "Blu-ray", "blu-ray": "Blu-ray",
    "br": "Blu-ray", "4k": "4K UHD", "br4k": "4K UHD", "4k uhd": "4K UHD", "uhd": "4K UHD",
    "digital": "Digital", "archivo": "Digital", "archivo digital": "Digital",
}


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
    clave = re.sub(r"[^A-Za-z0-9]+", "_", f"{ruta}_{consulta}")[:200]
    fichero = os.path.join(CACHE, clave + ".json")
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
    i_ano = columna(cab, "ano", "anio", "year")
    i_not = columna(cab, "notas", "nota", "observaciones", "comentarios")
    if i_not is None and len(cab) > 2 and not cab[-1].strip():
        i_not = len(cab) - 1  # columna sin cabecera al final: se usa para notas
    if i_tit is None:
        sys.exit(f"No encuentro la columna de título en: {cab}")
    val = lambda fila, i: fila[i].strip() if i is not None and i < len(fila) else ""

    copias = []
    for n, fila in enumerate(filas[1:], start=2):
        titulo = val(fila, i_tit)
        if not titulo:
            continue
        formato_bruto = val(fila, i_for)
        clave_f = normalizar(formato_bruto)
        ano = re.search(r"(18|19|20)\d\d", val(fila, i_ano))
        copias.append({
            "fila": n,
            "titulo": titulo,
            "formato": FORMATOS.get(clave_f, FORMATOS.get(clave_f.replace(" ", ""), formato_bruto)),
            "anio": int(ano.group()) if ano else None,
            "notas": val(fila, i_not),
        })
    return copias


def leer_correcciones():
    ruta = os.path.join(DATOS, "correcciones.csv")
    correcciones = {}
    if os.path.exists(ruta):
        with open(ruta, newline="", encoding="utf-8-sig") as f:
            for c in csv.DictReader(f):
                ano = (c.get("anio") or "").strip()
                correcciones[(normalizar(c["titulo"]), int(ano) if ano else None)] = c["tmdb_id"].strip()
    return correcciones


def puntuar(candidato, titulo, anio):
    """0..1: parecido del título (español u original) y cercanía del año."""
    t = normalizar(titulo)
    parecido = 0
    for nombre in (normalizar(candidato.get("title")), normalizar(candidato.get("original_title"))):
        parecido = max(parecido, SequenceMatcher(None, t, nombre).ratio())
        # Título abreviado en la hoja («Juergas universitarias», «Master & Commander»)
        palabras = set(t.split()) - {"y", "and"}
        if len(palabras) >= 2 and palabras <= set(nombre.split()):
            parecido = max(parecido, 0.88)
    ano_c = (candidato.get("release_date") or "")[:4]
    if anio and ano_c.isdigit():
        diferencia = abs(int(ano_c) - anio)
        parecido *= 1.0 if diferencia == 0 else 0.9 if diferencia == 1 else 0.5
    return parecido


def variantes(titulo):
    """El título tal cual, sin lo que va entre paréntesis, lo de dentro, y cada lado de una barra."""
    limpio = lambda t: re.sub(r"\s+", " ", t.replace("?", "")).strip(" .-")
    salida = [titulo, re.sub(r"\(.*?\)", "", titulo), re.sub(r"\b(3D|007)\b", "", titulo)]
    salida += re.findall(r"\((.*?)\)", titulo)
    salida += titulo.split(" / ") if " / " in titulo else []
    vistas, unicas = set(), []
    for v in map(limpio, salida):
        if len(v) > 1 and normalizar(v) not in vistas:
            vistas.add(normalizar(v))
            unicas.append(v)
    return unicas


def buscar(titulo, anio):
    """Devuelve (tmdb_id o None, dudosa, candidatos ordenados)."""
    puntos, por_id = {}, {}
    for consulta in variantes(titulo):
        resultados = []
        if anio:
            resultados = tmdb("/search/movie", query=consulta, language="es-ES", year=anio)["results"]
        if not resultados:
            resultados = tmdb("/search/movie", query=consulta, language="es-ES")["results"]
        for c in resultados[:10]:
            por_id.setdefault(c["id"], c)
            puntos[c["id"]] = max(puntos.get(c["id"], 0), puntuar(c, consulta, anio))
        if puntos and max(puntos.values()) >= 0.85:
            break
    candidatos = sorted(por_id.values(), key=lambda c: -puntos[c["id"]])
    if not candidatos or puntos[candidatos[0]["id"]] < 0.85:
        return None, False, candidatos[:5]
    # Empates de título (remakes, secuelas con el mismo original): gana la más conocida,
    # pero si la otra también lo es, se marca como dudosa para comprobarla.
    empatados = [c for c in candidatos if puntos[candidatos[0]["id"]] - puntos[c["id"]] < 0.1]
    empatados.sort(key=lambda c: -c.get("vote_count", 0))
    elegida = empatados[0]
    dudosa = any(c.get("vote_count", 0) >= 0.2 * max(elegida.get("vote_count", 0), 1)
                 for c in empatados[1:])
    candidatos.remove(elegida)
    return elegida["id"], dudosa, [elegida] + candidatos[:4]


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


def ficha(tmdb_id):
    d = tmdb(f"/movie/{tmdb_id}", language="es-ES", append_to_response="credits")
    sinopsis = d.get("overview")
    if not sinopsis:
        sinopsis = tmdb(f"/movie/{tmdb_id}", language="en-US").get("overview")
    equipo = d.get("credits", {}).get("crew", [])
    unicos = lambda xs: list(dict.fromkeys(xs))
    return {
        "tmdb_id": d["id"],
        "titulo": d.get("title"),
        "titulo_original": d.get("original_title"),
        "anio": int(d["release_date"][:4]) if d.get("release_date") else None,
        "duracion": d.get("runtime"),
        "generos": [g["name"] for g in d.get("genres", [])],
        "director": unicos(p["name"] for p in equipo if p.get("job") == "Director"),
        "guion": unicos(p["name"] for p in equipo if p.get("department") == "Writing")[:4],
        "reparto": [p["name"] for p in d.get("credits", {}).get("cast", [])[:8]],
        "sinopsis": sinopsis,
        "caratula": f"https://image.tmdb.org/t/p/w500{d['poster_path']}" if d.get("poster_path") else None,
    }


def main():
    hoja = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DATOS, "hoja.csv")
    copias = leer_hoja(hoja)
    correcciones = leer_correcciones()

    # Una película puede tener varias copias: agrupar por título + año escritos.
    grupos = {}
    for c in copias:
        grupos.setdefault((normalizar(c["titulo"]), c["anio"]), []).append(c)

    peliculas, por_id, revisar = [], {}, []

    def anadir(tmdb_id, copias_ficha, dudosa):
        if tmdb_id not in por_id:
            por_id[tmdb_id] = ficha(tmdb_id)
            por_id[tmdb_id]["copias"] = []
            peliculas.append(por_id[tmdb_id])
        p = por_id[tmdb_id]
        p["copias"].extend(copias_ficha)
        if dudosa:
            p["comprobar"] = True
        return p

    for n, ((clave_t, anio), grupo) in enumerate(grupos.items(), start=1):
        titulo = grupo[0]["titulo"]
        copias_ficha = [{"formato": c["formato"], "notas": c["notas"], "titulo_hoja": c["titulo"]}
                        for c in grupo]
        print(f"[{n}/{len(grupos)}] {titulo}", end="  ", flush=True)

        forzado = correcciones.get((clave_t, anio))
        filas = " ".join(str(c["fila"]) for c in grupo)
        inedita = forzado == "manual" or any("inedit" in normalizar(c["notas"]) for c in grupo)
        if inedita:
            print("→ inédita (ficha manual)")
            peliculas.append({"tmdb_id": None, "titulo": titulo, "anio": anio, "manual": True,
                              "copias": copias_ficha})
            continue

        if not forzado and "ilegible" in clave_t:
            print("→ ILEGIBLE")
            revisar.append({"estado": "ilegible", "titulo": titulo, "anio": "", "filas": filas,
                            "candidatos": ""})
            peliculas.append({"tmdb_id": None, "titulo": titulo, "anio": anio, "pendiente": True,
                              "copias": copias_ficha})
            continue

        if not forzado and PACK.search(clave_t):
            nombre, ids = buscar_pack(titulo)
            if ids:
                nota = f"Pack: {titulo}"
                for tmdb_id in ids:
                    anadir(tmdb_id, [dict(c, notas="; ".join(x for x in (nota, c["notas"]) if x))
                                     for c in copias_ficha], False)
                print(f"→ pack «{nombre}»: " + ", ".join(por_id[i]["titulo"] for i in ids))
                continue

        tmdb_id, dudosa, candidatos = (int(forzado), False, []) if forzado else buscar(titulo, anio)
        if not tmdb_id or dudosa:
            print("→ DUDOSA" if dudosa else "→ SIN ELEGIR", end="  " if dudosa else "\n")
            revisar.append({
                "estado": "comprobar" if dudosa else "sin elegir",
                "titulo": titulo, "anio": anio or "", "filas": filas,
                "candidatos": " | ".join(
                    f"{c['id']}: {c.get('title')} ({(c.get('release_date') or '????')[:4]})"
                    for c in candidatos) or "sin resultados",
            })
        if not tmdb_id:
            peliculas.append({"tmdb_id": None, "titulo": titulo, "anio": anio, "pendiente": True,
                              "copias": copias_ficha})
            continue

        repetida = tmdb_id in por_id  # "Alien" y "Alien, el octavo pasajero" son la misma película
        p = anadir(tmdb_id, copias_ficha, dudosa)
        print(f"→ misma película que «{p['titulo']}»" if repetida else f"→ {p['titulo']} ({p['anio']})")

    with open(os.path.join(DATOS, "peliculas.json"), "w", encoding="utf-8") as f:
        json.dump(peliculas, f, ensure_ascii=False, indent=1)
    with open(os.path.join(DATOS, "revisar.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["estado", "titulo", "anio", "filas", "candidatos"])
        w.writeheader()
        w.writerows(revisar)

    encontradas = sum(1 for p in peliculas if p.get("tmdb_id"))
    print(f"\n{len(copias)} copias → {len(peliculas)} películas: "
          f"{encontradas} con ficha ({sum(1 for p in peliculas if p.get('comprobar'))} dudosas), "
          f"{sum(1 for p in peliculas if p.get('pendiente'))} sin elegir, "
          f"{sum(1 for p in peliculas if p.get('manual'))} inéditas.")


if __name__ == "__main__":
    main()
