-- Videoclub: esquema. Pegar entero en Supabase → SQL Editor → Run. Se puede ejecutar más de una vez.

-- Una fila por película; sus copias físicas (formato + notas) van dentro, en `copias`.
create table if not exists public.peliculas (
  id              bigint generated always as identity primary key,
  tmdb_id         integer unique,                 -- null en inéditas y pendientes
  titulo          text not null,
  titulo_original text,
  anio            integer,
  duracion        integer,                        -- minutos
  generos         text[] not null default '{}',
  director        text[] not null default '{}',
  guion           text[] not null default '{}',
  reparto         text[] not null default '{}',
  sinopsis        text,
  caratula        text,                           -- URL de la imagen
  copias          jsonb  not null default '[]',   -- [{formato, notas, titulo_hoja}]
  estado          text   not null default 'ok'
                  check (estado in ('ok', 'comprobar', 'pendiente', 'manual')),
  candidatos      jsonb  not null default '[]',   -- alternativas de TMDB para revisar
  creada          timestamptz not null default now(),
  actualizada     timestamptz not null default now()
);

create or replace function public.tocar_actualizada() returns trigger
language plpgsql as $$
begin
  new.actualizada := now();
  return new;
end $$;

drop trigger if exists peliculas_actualizada on public.peliculas;
create trigger peliculas_actualizada before update on public.peliculas
  for each row execute function public.tocar_actualizada();

-- Todo el mundo consulta; solo quien ha iniciado sesión (tú) modifica.
-- Para que nadie más pueda tener sesión: Authentication → Sign In / Providers → desactivar
-- "Allow new users to sign up".
alter table public.peliculas enable row level security;

drop policy if exists "consultar" on public.peliculas;
create policy "consultar" on public.peliculas
  for select to anon, authenticated using (true);

drop policy if exists "editar" on public.peliculas;
create policy "editar" on public.peliculas
  for all to authenticated using (true) with check (true);

-- Ajustes privados (la clave de TMDB para dar de alta películas): solo con sesión iniciada.
create table if not exists public.ajustes (
  clave text primary key,
  valor text not null
);

alter table public.ajustes enable row level security;

drop policy if exists "leer con sesion" on public.ajustes;
create policy "leer con sesion" on public.ajustes
  for select to authenticated using (true);
