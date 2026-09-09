-- ---------------------------------------------------------------------
-- Multi-calendario de Google
--
-- La vista mezcla TODOS los calendarios del usuario, no solo el principal:
-- leer solo `primary` hacia que el horario de quien lo tiene en un
-- calendario secundario (trabajo, universidad) pareciera "aparecer desde el
-- mes siguiente".
--
-- Dos tablas cambian de clave:
--
-- - google_events: el id de evento solo es unico dentro de su calendario,
--   asi que la identidad de una fila pasa a ser (user_id, calendar_id,
--   event_id).
-- - sync_tokens: Google entrega UN syncToken POR calendario (usarlo cruzado
--   devuelve mal los cambios), asi que la marca pasa a ser una fila por
--   (user_id, calendar_id).
--
-- Un calendario compartido aparece dos veces (una por calendario) con el
-- mismo inicio/fin/titulo; la deduplicacion ocurre en el servicio, la base
-- guarda la copia por calendario y punto.
-- ---------------------------------------------------------------------

alter table public.google_events
  add column if not exists calendar_id text not null default 'primary';

-- La clave vieja era (user_id, event_id); pasa a (user_id, calendar_id, event_id).
alter table public.google_events
  drop constraint if exists google_events_pkey;
alter table public.google_events
  add primary key (user_id, calendar_id, event_id);

alter table public.sync_tokens
  add column if not exists calendar_id text not null default 'primary';

alter table public.sync_tokens
  drop constraint if exists sync_tokens_pkey;
alter table public.sync_tokens
  add primary key (user_id, calendar_id);

-- El rango sigue consultandose por (user_id, inicio): el indice viejo sigue
-- sirviendo tal cual, la nueva columna no cambia la forma del query.