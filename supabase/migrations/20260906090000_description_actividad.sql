-- ---------------------------------------------------------------------
-- Descripcion opcional de una actividad
--
-- La app pide una nota libre ("para qué es esto") que no participa del
-- solver: ni la fija ni la flexible la usan para ubicar la actividad. Es
-- información para la persona, y por eso viaja como texto plano que el
-- cliente muestra tal cual. null = no hay descripcion, no "sin nota".
-- ---------------------------------------------------------------------

alter table public.activities
  add column if not exists description text;

-- No lleva índice: la descripción nunca se filtra ni se agrupa, solo se
-- guarda y se devuelve junto a su actividad.