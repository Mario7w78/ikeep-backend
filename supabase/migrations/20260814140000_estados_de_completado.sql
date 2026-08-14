-- ---------------------------------------------------------------------
-- Separar «no» de «no sé»
--
-- Hasta ahora una ocurrencia estaba marcada o no lo estaba. Esa binariedad
-- es la causa de todos los casos raros: el teléfono apagado, el día que se
-- abre a las once de la noche, la semana de parciales. Una actividad sin
-- marcar se parecía a una no hecha, y no son lo mismo.
--
-- «Sin resolver» NO es un valor de esta columna. Es la AUSENCIA de fila: no
-- se puede escribir "no sé" en la base porque nadie lo afirmó nunca. Guardar
-- un `sin_resolver` explícito obligaría a crear filas para cada ocurrencia
-- que pasa, y a decidir cuándo crearlas —cosa que solo el cliente sabe.
--
-- Ninguno de los dos cambios rompe lo construido: la tabla sigue igual y
-- gana dos columnas con default.
-- ---------------------------------------------------------------------

do $$
begin
  if not exists (select 1 from pg_type where typname = 'estado_completado') then
    create type public.estado_completado as enum ('hecha', 'no_hecha');
  end if;

  if not exists (select 1 from pg_type where typname = 'origen_completado') then
    -- No hay 'automatico' a propósito. Nunca se marca como hecha sola: la
    -- correlación entre energía y cumplimiento es lo único que esta app
    -- puede hacer y ninguna app de hábitos puede, y rellenarla con
    -- suposiciones la vuelve inservible.
    create type public.origen_completado as enum ('sesion', 'manual', 'cierre');
  end if;
end $$;

alter table public.activity_completions
  -- Las filas que ya existen son todas afirmaciones de "lo hice": era lo
  -- único que la app permitía decir.
  add column if not exists estado public.estado_completado not null default 'hecha',
  -- Y todas vinieron del check manual, que era el único camino.
  add column if not exists origen public.origen_completado not null default 'manual';

-- El progreso del día y el cierre consultan «lo hecho de esta fecha», que
-- ahora es un subconjunto de las filas y no todas. Sin esto, cada apertura
-- de la app filtra en memoria lo que la base puede descartar.
create index if not exists activity_completions_user_fecha_estado_idx
  on public.activity_completions (user_id, fecha desc, estado);
