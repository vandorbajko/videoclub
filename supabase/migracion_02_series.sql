-- Migracion 02: series ademas de peliculas.
-- Un mismo numero de TMDB puede ser una pelicula y una serie distintas,
-- asi que la clave unica pasa a ser (tipo, tmdb_id). Se puede ejecutar mas de una vez.
alter table public.peliculas add column if not exists tipo text not null default 'pelicula';
alter table public.peliculas drop constraint if exists peliculas_tipo_check;
alter table public.peliculas add constraint peliculas_tipo_check check (tipo in ('pelicula', 'serie'));
alter table public.peliculas drop constraint if exists peliculas_tmdb_id_key;
alter table public.peliculas drop constraint if exists peliculas_tipo_tmdb_id_key;
alter table public.peliculas add constraint peliculas_tipo_tmdb_id_key unique (tipo, tmdb_id);
