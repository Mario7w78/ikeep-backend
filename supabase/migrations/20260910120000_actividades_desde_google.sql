-- Actividades materializadas desde Google Calendar.
--
-- Hasta ahora los eventos de Google vivían solo en google_events (un cache
-- para pintar la vista mensual) y nunca llegaban a activities: la vista
-- mensual los mostraba con su punto gris, pero el calendario propio, el
-- horario y las actividades no los veían, y el usuario conectaba sin que
-- "pasara nada".
--
-- Esta migración vincula activities con su evento de origen. Las columnas
-- son NULL para las actividades creadas a mano (la inmensa mayoría) y solo
-- las importadas cargan google_event_id + google_calendar_id.
--
-- El índice único PARCIAL es la red anti-duplicación: un mismo evento real
-- (mismo calendario + mismo event_id) del mismo usuario solo puede materiali-
-- zarse una vez. Las filas con google_event_id NULL (creadas a mano) no
-- colisionan entre sí ni con las importadas. NULL != NULL en Postgres, por
-- eso el índice es parcial y no un UNIQUE simple.

alter table public.activities
    add column if not exists google_event_id text;

alter table public.activities
    add column if not exists google_calendar_id text;

create unique index if not exists activities_google_import_idx
    on public.activities (user_id, google_calendar_id, google_event_id)
    where google_event_id is not null;