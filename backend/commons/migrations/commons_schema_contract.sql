-- Commons schema attestation. This is intentionally separate from Dice's
-- project schema contract because Commons owns the home scene.
do $$
declare
  object_name text;
begin
  foreach object_name in array array[
    'commons_scenes',
    'commons_scene_commands'
  ] loop
    if to_regclass('public.' || object_name) is null then
      raise exception 'Commons schema contract: missing table public.%', object_name;
    end if;
  end loop;

  if to_regprocedure('public.commons_apply_command(text,text,text,integer,jsonb,jsonb)') is null then
    raise exception 'Commons schema contract: missing command function';
  end if;

  foreach object_name in array array[
    'commons_scenes',
    'commons_scene_commands'
  ] loop
    if not (
      select relrowsecurity
        from pg_class
       where oid = ('public.' || object_name)::regclass
    ) then
      raise exception 'Commons schema contract: RLS disabled on public.%', object_name;
    end if;
  end loop;
end;
$$;
