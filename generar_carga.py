#!/usr/bin/env python3
"""Genera supabase/carga.sql a partir de datos/peliculas.json, para pegarlo en el SQL Editor.

Es una carga inicial: se niega a ejecutarse si la tabla ya tiene películas.
"""
import json
import os

RAIZ = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(RAIZ, "datos", "peliculas.json"), encoding="utf-8") as f:
    peliculas = json.load(f)

datos = json.dumps(peliculas, ensure_ascii=False, separators=(",", ":"))
assert "$datos$" not in datos

sql = f"""-- Carga inicial del videoclub ({len(peliculas)} películas). Pegar en SQL Editor → Run.
do $$
begin
  if exists (select 1 from public.peliculas) then
    raise exception 'La tabla peliculas ya tiene datos: la carga inicial no se repite.';
  end if;
end $$;

insert into public.peliculas
  (tmdb_id, titulo, titulo_original, anio, duracion, generos, director, guion, reparto,
   sinopsis, caratula, copias, estado, candidatos)
select tmdb_id, titulo, titulo_original, anio, duracion,
       coalesce(generos, '{{}}'), coalesce(director, '{{}}'), coalesce(guion, '{{}}'),
       coalesce(reparto, '{{}}'), sinopsis, caratula, copias, estado, coalesce(candidatos, '[]')
from jsonb_to_recordset($datos${datos}$datos$::jsonb) as p(
  tmdb_id integer, titulo text, titulo_original text, anio integer, duracion integer,
  generos text[], director text[], guion text[], reparto text[], sinopsis text,
  caratula text, copias jsonb, estado text, candidatos jsonb);

select estado, count(*) from public.peliculas group by estado order by estado;
"""

salida = os.path.join(RAIZ, "supabase", "carga.sql")
with open(salida, "w", encoding="utf-8") as f:
    f.write(sql)
print(f"{salida}: {len(peliculas)} películas, {len(sql) // 1024} KB")
