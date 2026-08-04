-- El cliente lee schedules.created_at al cargar el horario (Schedule.createdAt
-- es un Date obligatorio de la entidad), pero el esquema inicial solo declaro
-- updated_at. Sin la columna, `new Date(undefined)` produce un Invalid Date
-- que no lanza: se propaga en silencio y aparece mucho despues, al mostrar
-- una fecha.
--
-- Se derivo el esquema del codigo del frontend y esta columna se leia en un
-- lugar distinto del que armaba la fila, asi que no aparecio en el mapeo.

alter table public.schedules
  add column if not exists created_at timestamptz not null default now();
