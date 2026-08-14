-- ---------------------------------------------------------------------
-- Las áreas de vida — los pétalos del loto
--
-- `identity` hacía tres trabajos y ninguno bien: era el ícono, el color, y
-- de paso decidía si el solver podía mover la actividad. Ese último uso
-- causaba un bug real —un turno de trabajo de 9 a 5 se reubicaba solo, por
-- no llamarse "clase"— que ya se arregló leyendo el comportamiento.
--
-- Lo que queda es la pregunta que sí importa y que `identity` nunca supo
-- responder: ¿de qué parte de tu vida es esto? La app no es solo estudio.
-- Sin esta columna no hay forma de mostrar que alguien lleva treinta días
-- seguidos estudiando y hace tres semanas que no se mueve ni ve a nadie.
--
-- Cinco áreas, y ese es el techo. Un loto de doce pétalos no se lee a 72 px
-- y cada área nueva diluye a las demás; si hiciera falta otra, hay que
-- quitar una.
-- ---------------------------------------------------------------------

do $$
begin
  if not exists (select 1 from pg_type where typname = 'area_de_vida') then
    create type public.area_de_vida as enum (
      'estudio',   -- clases, tareas, exámenes
      'trabajo',   -- lo que haces por obligación remunerada
      'cuerpo',    -- moverte, dormir, comer
      'vinculos',  -- ver gente, llamar, salir
      'yo'         -- leer, música, no hacer nada
    );
  end if;
end $$;

alter table public.activities
  add column if not exists area public.area_de_vida not null default 'estudio';

-- Se deriva de lo que ya había. No es una traducción exacta —`identity` no
-- distinguía leer por gusto de estudiar— pero es lo único que el dato viejo
-- permite afirmar, y el usuario puede corregirlo desde la app.
--
-- Solo toca las filas que aún tienen el valor por defecto: si esta migración
-- se corre dos veces, no pisa lo que la persona ya eligió.
update public.activities
   set area = case identity
                when 'trabajo' then 'trabajo'::public.area_de_vida
                else 'estudio'::public.area_de_vida
              end
 where area = 'estudio'
   and identity = 'trabajo';

-- El equilibrio se consulta por área y por usuario: cuánto hay de cada
-- pétalo. Sin este índice esa pantalla hace un seq scan por cada apertura.
create index if not exists activities_user_area_idx
  on public.activities (user_id, area);

-- `identity` NO se elimina todavía. Sigue habiendo clientes instalados que
-- la mandan, y la columna es `not null`: borrarla ahora rompe cada alta
-- desde una versión anterior. Se quita cuando nada la escriba.
comment on column public.activities.identity is
  'OBSOLETA. Reemplazada por `area` (de qué parte de tu vida) y por el
   comportamiento (si se puede mover). Se conserva solo para no romper
   clientes viejos; no leerla en código nuevo.';
