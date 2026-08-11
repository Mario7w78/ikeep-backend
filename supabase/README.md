# Migraciones

Este es el **único** lugar donde viven las migraciones. Hubo una segunda copia
en `ikeep-app/supabase/` —del 2026-07-31, de la integración original— que se
eliminó el 2026-08-11: describía tipos de columna que no coinciden ni con el
código ni con la base viva.

| Columna | La copia vieja | Lo que hay acá y en el código |
|---|---|---|
| `activities.deadline` | `timestamptz` | `text` — `ActivityPayload.deadline` es `str \| None` |
| `activities.day_from` / `day_to` | `text` | `smallint` — el dominio los tiene como `int \| None` |
| Políticas RLS | 7 | 20 — cuatro por tabla |

Además el esquema de acá es idempotente (`if not exists`, `create or replace`,
`drop trigger if exists`), así que volver a correrlo no rompe nada.

## El estado del proyecto remoto

El esquema se aplicó **a mano en el SQL Editor**, no por el CLI. Eso significa
que la tabla `supabase_migrations.schema_migrations` del proyecto remoto no
tiene registro de estos archivos, aunque su contenido sí esté aplicado.

Consecuencia: **`supabase db push` intentaría correr las cuatro migraciones
desde cero.** Las tablas sobrevivirían por los `if not exists`, pero los
`create policy` no llevan guard y fallaría con `policy already exists`.

## Cómo dejar el CLI utilizable

Estos pasos los tiene que correr una persona: `link` pide la contraseña de la
base de datos.

```bash
# 1. Vincular. El project-ref es el subdominio de tu SUPABASE_URL.
supabase link --project-ref <tu-project-ref>

# 2. Decirle a Supabase que estas tres YA están aplicadas, sin volver a correrlas.
supabase migration repair --status applied 20260803120000
supabase migration repair --status applied 20260803150000
supabase migration repair --status applied 20260803180000

# 3. Comprobar que solo queda pendiente la nueva.
supabase migration list

# 4. Recién ahora.
supabase db push
```

Si `migration list` muestra alguna de las tres primeras como pendiente después
del paso 2, **no** sigas con el push: significa que el remoto no tiene lo que
creemos que tiene, y conviene mirar el esquema real antes de escribir.

## Mientras tanto

Para una sola migración no hace falta nada de lo anterior. Al SQL Editor:

```bash
pbcopy < supabase/migrations/20260811090000_activity_completions.sql
```
