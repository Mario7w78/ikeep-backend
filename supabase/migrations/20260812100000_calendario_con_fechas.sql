-- ---------------------------------------------------------------------
-- El calendario con fechas reales
--
-- Hasta ahora una actividad guardaba dias de la semana y esa semana se
-- repetia indefinidamente. Servia para generar un horario, pero no para un
-- calendario: un parcial el 12 de noviembre no se podia representar y "este
-- martes no hay clase" no tenia donde vivir.
--
-- El modelo es el de Google Calendar y el de Apple: se guarda la regla y las
-- excepciones, y las fechas se derivan al vuelo. La alternativa —una fila por
-- cada repeticion— obliga a elegir hasta cuando materializar y a regenerar
-- todo cada vez que el usuario cambia un dia.
-- ---------------------------------------------------------------------

-- Un evento que ocurre una sola vez. Cuando esta puesta, los dias de la
-- semana no aplican: un evento unico que ademas se repite no significa nada.
alter table public.activities
  add column if not exists fecha_unica date;

-- Solo hace falta para el calendario, que siempre consulta por rango.
create index if not exists activities_fecha_unica_idx
  on public.activities (user_id, fecha_unica)
  where fecha_unica is not null;


-- ---------------------------------------------------------------------
-- activity_exceptions
--
-- Lo que rompe la regla en una fecha puntual. `cancelada` es "este martes no
-- hay clase"; `movida` pasa esa ocurrencia a otro dia y necesita nueva_fecha.
--
-- La fecha original es parte de la clave: una actividad puede tener una
-- excepcion por ocurrencia, y no mas de una para la misma.
-- ---------------------------------------------------------------------
create table if not exists public.activity_exceptions (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users (id) on delete cascade,
  activity_id  text not null references public.activities (id) on delete cascade,
  -- El dia en que la regla decia que ocurria.
  fecha        date not null,
  tipo         text not null check (tipo in ('cancelada', 'movida')),
  -- Solo para 'movida'. La restriccion de abajo lo obliga.
  nueva_fecha  date,
  creado_en    timestamptz not null default now(),

  unique (user_id, activity_id, fecha),

  -- Una excepcion 'movida' sin destino dejaria la ocurrencia en la nada, y
  -- una 'cancelada' con destino es una contradiccion. Las dos se rechazan
  -- aca y no en el codigo: la base es el ultimo lugar donde el dato puede
  -- quedar incoherente.
  constraint destino_coherente check (
    (tipo = 'movida'    and nueva_fecha is not null) or
    (tipo = 'cancelada' and nueva_fecha is null)
  )
);

-- El calendario consulta por usuario y rango de fechas.
create index if not exists activity_exceptions_user_fecha_idx
  on public.activity_exceptions (user_id, fecha);

alter table public.activity_exceptions enable row level security;

create policy "Usuarios ven sus excepciones"
  on public.activity_exceptions for select to authenticated
  using (auth.uid() = user_id);

create policy "Usuarios crean sus excepciones"
  on public.activity_exceptions for insert to authenticated
  with check (auth.uid() = user_id);

create policy "Usuarios editan sus excepciones"
  on public.activity_exceptions for update to authenticated
  using (auth.uid() = user_id);

create policy "Usuarios borran sus excepciones"
  on public.activity_exceptions for delete to authenticated
  using (auth.uid() = user_id);
