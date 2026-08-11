-- ---------------------------------------------------------------------
-- activity_completions
--
-- El plan original pedia un campo `completed_at` en `activities`. No sirve:
-- una actividad es una definicion recurrente —"Calculo, martes y jueves"—,
-- no una ocurrencia. Marcarla completada el martes la dejaria completada
-- para siempre, y el jueves ya no habria nada que completar.
--
-- Una fila por (actividad, dia) es lo que hace posible todo lo demas: la
-- racha necesita saber que dias hubo al menos una, y el progreso diario
-- necesita contar las de hoy. Con un solo campo en `activities` ninguna de
-- las dos se puede calcular.
--
-- `fecha` es date y no timestamptz a proposito: "lo completo hoy" es una
-- afirmacion sobre el dia del usuario, no sobre un instante. El cliente
-- manda su fecha local, porque el servidor no puede saberla —el mismo error
-- que ya tiene GET /energia/hoy usando medianoche UTC.
-- ---------------------------------------------------------------------
create table if not exists public.activity_completions (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users (id) on delete cascade,
  -- Si la actividad se borra, sus completados se van con ella: sin la
  -- definicion, la fila no significa nada.
  activity_id  text not null references public.activities (id) on delete cascade,
  fecha        date not null,
  completed_at timestamptz not null default now(),

  -- Completar dos veces el mismo dia es la misma afirmacion, no dos. El
  -- upsert del cliente se apoya en esto.
  unique (user_id, activity_id, fecha)
);

-- La racha y el progreso diario recorren por usuario y fecha descendente.
create index if not exists activity_completions_user_fecha_idx
  on public.activity_completions (user_id, fecha desc);

alter table public.activity_completions enable row level security;

create policy "Usuarios ven sus completados"
  on public.activity_completions for select to authenticated
  using (auth.uid() = user_id);

create policy "Usuarios registran sus completados"
  on public.activity_completions for insert to authenticated
  with check (auth.uid() = user_id);

create policy "Usuarios editan sus completados"
  on public.activity_completions for update to authenticated
  using (auth.uid() = user_id);

create policy "Usuarios borran sus completados"
  on public.activity_completions for delete to authenticated
  using (auth.uid() = user_id);
