#!/usr/bin/env python3
"""Genera supabase/carga.sql a partir de datos/peliculas.json, para pegarlo en el SQL Editor.

    python3 generar_carga.py               carga inicial: se niega si la tabla ya tiene datos
    python3 generar_carga.py --reemplazar  borra todo el catálogo y lo vuelve a cargar
"""
import json
import os
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(RAIZ, "datos", "peliculas.json"), encoding="utf-8") as f:
    peliculas = json.load(f)

# Solo ASCII (tildes escritas como \u00ed): así el portapapeles o el editor no pueden estropear los textos.
datos = json.dumps(peliculas, ensure_ascii=True, separators=(",", ":"))
assert "$datos$" not in datos

if "--reemplazar" in sys.argv:
    cabecera = f"""-- Recarga del videoclub ({len(peliculas)} fichas): borra el catalogo y lo vuelve a cargar.
delete from public.peliculas where id > 0;
"""
else:
    cabecera = f"""-- Carga inicial del videoclub ({len(peliculas)} fichas). Pegar en SQL Editor y pulsar Run.
do $$
begin
  if exists (select 1 from public.peliculas) then
    raise exception 'La tabla peliculas ya tiene datos: la carga inicial no se repite.';
  end if;
end $$;
"""

sql = cabecera + f"""
insert into public.peliculas
  (tipo, tmdb_id, titulo, titulo_original, anio, duracion, generos, director, guion, reparto,
   sinopsis, caratula, copias, estado, candidatos)
select coalesce(tipo, 'pelicula'), tmdb_id, titulo, titulo_original, anio, duracion,
       coalesce(generos, '{{}}'), coalesce(director, '{{}}'), coalesce(guion, '{{}}'),
       coalesce(reparto, '{{}}'), sinopsis, caratula, copias, estado, coalesce(candidatos, '[]')
from jsonb_to_recordset($datos${datos}$datos$::jsonb) as p(
  tipo text, tmdb_id integer, titulo text, titulo_original text, anio integer, duracion integer,
  generos text[], director text[], guion text[], reparto text[], sinopsis text,
  caratula text, copias jsonb, estado text, candidatos jsonb);

select estado, count(*) from public.peliculas group by estado order by estado;
"""

salida = os.path.join(RAIZ, "supabase", "carga.sql")
with open(salida, "w", encoding="utf-8") as f:
    f.write(sql)
assert sql.isascii()
print(f"{salida}: {len(peliculas)} fichas, {len(sql) // 1024} KB")
