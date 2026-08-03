-- =====================================================================
-- Kerotime — esquema inicial
--
-- Derivado del código del frontend, que es hoy la única especificación
-- del esquema: los nombres de columna salen de los objetos que se mandan
-- a PostgREST (activityToRow, upsertSettings, saveScheduleToStorage...).
--
-- Correr entero en el SQL Editor de Supabase. Es idempotente salvo por
-- el DROP inicial.
-- =====================================================================

-- Tabla huérfana: la creó el diseño viejo del backend (el módulo muerto
-- de SQLAlchemy declara __tablename__ = "actividades"). Nada en la app
-- la consulta — el frontend pide "activities", en inglés.
drop table if exists public.actividades cascade;


-- ---------------------------------------------------------------------
-- profiles
-- La PK es el propio id de auth.users, no una columna user_id aparte:
-- SupabaseUserRepository filtra por .eq('id', authUser.id).
-- ---------------------------------------------------------------------
create table if not exists public.profiles (
  id            uuid primary key references auth.users (id) on delete cascade,
  username      text,
  energy_level  smallint,
  -- Horas guardadas como texto ("07:30"), no como time: el dominio las
  -- trata como string y las compara por truthiness.
  wake_up_time  text,
  sleep_time    text,
  updated_at    timestamptz not null default now()
);


-- ---------------------------------------------------------------------
-- activities
-- id es text, no uuid: los ids los genera el cliente y no son uuids.
-- ---------------------------------------------------------------------
create table if not exists public.activities (
  id            text primary key,
  user_id       uuid not null references auth.users (id) on delete cascade,
  title         text not null,
  type          text not null,
  identity      text not null default 'tarea',
  priority      smallint not null default 3,
  difficulty    text not null default 'media',
  deadline      text,
  -- jsonb en vez de text[]/int[]: el cliente manda y recibe estructuras
  -- anidadas (days_config lleva particiones con fechas serializadas).
  days_enabled  jsonb not null default '[]'::jsonb,
  days_config   jsonb not null default '{}'::jsonb,
  optional_day  boolean not null default false,
  day_from      smallint,
  day_to        smallint,
  is_anchor     boolean not null default false,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists activities_user_id_idx
  on public.activities (user_id);


-- ---------------------------------------------------------------------
-- energy_records
-- "timestamp" va entre comillas: es nombre de tipo en SQL y sin comillas
-- se vuelve ambiguo en varios contextos.
-- ---------------------------------------------------------------------
create table if not exists public.energy_records (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users (id) on delete cascade,
  "timestamp"  timestamptz not null,
  nivel        smallint not null,
  -- 0 = lunes … 6 = domingo (el cliente ya convierte desde el domingo=0 de JS)
  dia_semana   smallint not null,
  contexto     text
);

-- getEnergyHistory filtra por user_id + rango de timestamp y ordena desc.
create index if not exists energy_records_user_ts_idx
  on public.energy_records (user_id, "timestamp" desc);


-- ---------------------------------------------------------------------
-- user_settings
-- user_id es la PK porque upsertSettings hace conflicto sobre user_id.
-- Los defaults replican los del cliente (240 = 04:00, 1320 = 22:00).
-- ---------------------------------------------------------------------
create table if not exists public.user_settings (
  user_id                uuid primary key references auth.users (id) on delete cascade,
  start_hour             integer not null default 240,
  end_hour               integer not null default 1320,
  dia_inicio             smallint not null default 0,
  dias_totales           smallint not null default 7,
  per_day_start_hours    jsonb,
  per_day_end_hours      jsonb,
  custom_energy_pattern  text,
  updated_at             timestamptz not null default now()
);


-- ---------------------------------------------------------------------
-- schedules
-- user_id es unique, no PK: el upsert usa onConflict:'user_id' y Postgres
-- es dueño de su propio id (el Schedule.id del dominio, "schedule-<ts>",
-- no es un uuid válido). Un horario vigente por usuario.
-- ---------------------------------------------------------------------
create table if not exists public.schedules (
  id                    uuid primary key default gen_random_uuid(),
  user_id               uuid not null unique references auth.users (id) on delete cascade,
  estado                text,
  mensaje               text,
  recomendaciones       jsonb not null default '[]'::jsonb,
  tareas_omitidas       jsonb not null default '[]'::jsonb,
  scheduled_activities  jsonb not null default '[]'::jsonb,
  updated_at            timestamptz not null default now()
);


-- =====================================================================
-- Row Level Security
--
-- Sin políticas, RLS activa niega TODO (no abre nada). Cada tabla necesita
-- las cuatro. Se aplican a `authenticated` y no a `public`: toda operación
-- de la app exige sesión, así que ni vale evaluarlas para el rol anónimo.
--
-- En UPDATE se omite WITH CHECK a propósito: Postgres reusa la expresión
-- de USING para la fila resultante, lo que ya impide reasignarle la fila
-- a otro usuario.
-- =====================================================================

alter table public.profiles       enable row level security;
alter table public.activities     enable row level security;
alter table public.energy_records enable row level security;
alter table public.user_settings  enable row level security;
alter table public.schedules      enable row level security;

-- profiles: se scopea por id, no por user_id.
create policy "Usuarios ven su perfil"      on public.profiles for select to authenticated using (auth.uid() = id);
create policy "Usuarios crean su perfil"    on public.profiles for insert to authenticated with check (auth.uid() = id);
create policy "Usuarios editan su perfil"   on public.profiles for update to authenticated using (auth.uid() = id);
create policy "Usuarios borran su perfil"   on public.profiles for delete to authenticated using (auth.uid() = id);

create policy "Usuarios ven sus actividades"      on public.activities for select to authenticated using (auth.uid() = user_id);
create policy "Usuarios insertan sus actividades" on public.activities for insert to authenticated with check (auth.uid() = user_id);
create policy "Usuarios editan sus actividades"   on public.activities for update to authenticated using (auth.uid() = user_id);
create policy "Usuarios borran sus actividades"   on public.activities for delete to authenticated using (auth.uid() = user_id);

create policy "Usuarios ven su energia"      on public.energy_records for select to authenticated using (auth.uid() = user_id);
create policy "Usuarios registran su energia" on public.energy_records for insert to authenticated with check (auth.uid() = user_id);
create policy "Usuarios editan su energia"   on public.energy_records for update to authenticated using (auth.uid() = user_id);
create policy "Usuarios borran su energia"   on public.energy_records for delete to authenticated using (auth.uid() = user_id);

create policy "Usuarios ven sus ajustes"      on public.user_settings for select to authenticated using (auth.uid() = user_id);
create policy "Usuarios crean sus ajustes"    on public.user_settings for insert to authenticated with check (auth.uid() = user_id);
create policy "Usuarios editan sus ajustes"   on public.user_settings for update to authenticated using (auth.uid() = user_id);
create policy "Usuarios borran sus ajustes"   on public.user_settings for delete to authenticated using (auth.uid() = user_id);

create policy "Usuarios ven su horario"      on public.schedules for select to authenticated using (auth.uid() = user_id);
create policy "Usuarios crean su horario"    on public.schedules for insert to authenticated with check (auth.uid() = user_id);
create policy "Usuarios editan su horario"   on public.schedules for update to authenticated using (auth.uid() = user_id);
create policy "Usuarios borran su horario"   on public.schedules for delete to authenticated using (auth.uid() = user_id);


-- =====================================================================
-- Trigger de signup
--
-- SupabaseUserRepository asume que al registrarse ya existe una fila en
-- profiles con solo el id ("perfil incompleto"), y su delete() limpia
-- campos en vez de borrar la fila porque nada la recrearía.
--
-- security definer + search_path vacío es el endurecimiento que recomienda
-- Supabase: sin él, un search_path manipulado podría redirigir el insert.
-- Por eso todo va calificado con public.
-- =====================================================================

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id)
  values (new.id)
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;

create trigger on_auth_user_created
  after insert on auth.users
  for each row
  execute function public.handle_new_user();
