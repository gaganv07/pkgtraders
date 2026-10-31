-- VORTEXT AI live-feed storage. Browser roles receive no table grants.
create table if not exists public.vortext_trade_snapshots (
  bot_id text primary key check (bot_id ~ '^[A-Za-z0-9._-]{1,64}$'),
  captured_at timestamptz not null,
  snapshot jsonb not null check (pg_catalog.jsonb_typeof(snapshot) = 'object'),
  created_at timestamptz not null default pg_catalog.now(),
  updated_at timestamptz not null default pg_catalog.now()
);
alter table public.vortext_trade_snapshots enable row level security;
revoke all on table public.vortext_trade_snapshots from public, anon, authenticated;
grant usage on schema public to service_role;
grant select, insert, update, delete on table public.vortext_trade_snapshots to service_role;

create or replace function public.upsert_vortext_trade_snapshot(
  p_bot_id text, p_captured_at timestamptz, p_snapshot jsonb
) returns jsonb
language plpgsql
set search_path = ''
as $$
declare
  v_accepted boolean;
begin
  if p_bot_id is null or p_bot_id !~ '^[A-Za-z0-9._-]{1,64}$' then
    raise exception 'invalid bot id';
  end if;
  if p_captured_at is null or p_snapshot is null or pg_catalog.jsonb_typeof(p_snapshot) <> 'object' then
    raise exception 'invalid trade snapshot';
  end if;
  insert into public.vortext_trade_snapshots as current_row
    (bot_id, captured_at, snapshot, created_at, updated_at)
  values (p_bot_id, p_captured_at, p_snapshot, pg_catalog.now(), pg_catalog.now())
  on conflict (bot_id) do update
    set captured_at = excluded.captured_at,
        snapshot = excluded.snapshot,
        updated_at = pg_catalog.now()
    where current_row.captured_at < excluded.captured_at
  returning true into v_accepted;
  return pg_catalog.jsonb_build_object('accepted', coalesce(v_accepted, false));
end;
$$;
revoke all on function public.upsert_vortext_trade_snapshot(text, timestamptz, jsonb) from public, anon, authenticated;
grant execute on function public.upsert_vortext_trade_snapshot(text, timestamptz, jsonb) to service_role;
