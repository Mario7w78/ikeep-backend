-- ---------------------------------------------------------------------
-- Calendario de Google: tablas para importar eventos
--
-- Tres tablas y ninguna sorpresa:
--
-- - google_tokens guarda el refresh_token CIFRADO (Fernet) junto al access
--   token de corto plazo. Una fila por usuario: conectar de nuevo pisa la
--   fila, no acumula conexiones viejas.
-- - google_events es la copia local de los eventos del calendario primario.
--   La clave es (user_id, event_id) porque el id del evento solo es unico
--   dentro del calendario de cada uno.
-- - sync_tokens guarda el syncToken de la sincronizacion incremental de
--   Google. Es estado de conexion como el refresh token, no un evento.
--
-- Todo lleva RLS con auth.uid() = user_id: los eventos de alguien son suyos,
-- y el endpoint los sirve siempre con el JWT del que pide, nunca con uno
-- privilegiado.
-- ---------------------------------------------------------------------

create table if not exists public.google_tokens (
  user_id uuid primary key references auth.users(id) on delete cascade,
  -- El secreto de largo plazo. Nunca viaja ni se devuelve en claro.
  refresh_token_cifrado text not null,
  -- El de corto plazo, cacheado mientras dure para no refrescar en cada llamada.
  access_token text,
  access_expira_en timestamptz,
  actualizado_en timestamptz not null default now()
);

create table if not exists public.google_events (
  user_id uuid not null references auth.users(id) on delete cascade,
  event_id text not null,
  titulo text not null,
  inicio timestamptz not null,
  fin timestamptz not null,
  -- Los eventos de todo el dia no tienen hora: se dibujan por fecha.
  todo_el_dia boolean not null default false,
  primary key (user_id, event_id)
);

-- El mes que dibuja la app consulta por rango de fechas: sin este indice,
-- cada carga del calendario seria un escaneo de todos los eventos de todos.
create index if not exists google_events_user_rango_idx
  on public.google_events (user_id, inicio);

create table if not exists public.sync_tokens (
  user_id uuid primary key references auth.users(id) on delete cascade,
  -- Lo entrega Google en cada sincronizacion y sirve para pedir solo cambios.
  -- Cuando Google lo rechaza con 410, se borra y la proxima es completa.
  sync_token text not null,
  actualizado_en timestamptz default now()
);

alter table public.google_tokens enable row level security;
alter table public.google_events enable row level security;
alter table public.sync_tokens enable row level security;

create policy "propietario" on public.google_tokens
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
create policy "propietario" on public.google_events
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
create policy "propietario" on public.sync_tokens
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
