-- El trigger de alta corre dentro de la misma transaccion que inserta en
-- auth.users: si falla, el registro entero se revierte y el usuario ve
-- "Database error saving new user" sin ninguna pista de la causa.
--
-- Crear la fila de profiles es una comodidad, no un requisito: durante el
-- onboarding SupabaseUserRepository.save() hace upsert igual. No hay motivo
-- para que un fallo aca impida registrarse.
--
-- Se agrega el manejador de excepciones para que el trigger nunca bloquee el
-- alta. El warning queda en los logs de Postgres para poder diagnosticarlo.

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
exception
  when others then
    raise warning 'handle_new_user fallo para %: %', new.id, sqlerrm;
    return new;
end;
$$;
