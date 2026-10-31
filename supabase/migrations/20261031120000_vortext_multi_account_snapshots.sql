-- VORTEXT AI multi-account live feed schema and user access mapping.
-- All client browser roles receive no direct write access.

-- 1. Per-Account Live Snapshot Table
create table if not exists public.vortext_account_snapshots (
  bot_id text not null check (bot_id ~ '^[A-Za-z0-9._-]{1,64}$'),
  account_id text not null check (account_id ~ '^[A-Za-z0-9._-]{1,64}$'),
  login bigint not null,
  server text not null default '',
  currency text not null default 'USD',
  balance numeric(15,2) not null default 0.00,
  equity numeric(15,2) not null default 0.00,
  margin numeric(15,2) not null default 0.00,
  free_margin numeric(15,2) not null default 0.00,
  trade_mode text not null default 'DEMO',
  captured_at timestamptz not null,
  snapshot jsonb not null check (pg_catalog.jsonb_typeof(snapshot) = 'object'),
  created_at timestamptz not null default pg_catalog.now(),
  updated_at timestamptz not null default pg_catalog.now(),
  primary key (bot_id, account_id)
);

alter table public.vortext_account_snapshots enable row level security;
revoke all on table public.vortext_account_snapshots from public, anon, authenticated;
grant usage on schema public to service_role;
grant select, insert, update, delete on table public.vortext_account_snapshots to service_role;

-- 2. User Account Access Mapping Table
create table if not exists public.vortext_user_account_access (
  user_email text not null,
  account_id text not null check (account_id ~ '^[A-Za-z0-9._-]{1,64}$'),
  role text not null default 'viewer',
  created_at timestamptz not null default pg_catalog.now(),
  primary key (user_email, account_id)
);

alter table public.vortext_user_account_access enable row level security;
revoke all on table public.vortext_user_account_access from public, anon, authenticated;
grant usage on schema public to service_role;
grant select, insert, update, delete on table public.vortext_user_account_access to service_role;

-- 3. Upsert RPC supporting multi-account batching
create or replace function public.upsert_vortext_multi_account_snapshot(
  p_bot_id text,
  p_captured_at timestamptz,
  p_snapshot jsonb
) returns jsonb
language plpgsql
set search_path = ''
as $$
declare
  v_accepted boolean;
  v_acct jsonb;
begin
  if p_bot_id is null or p_bot_id !~ '^[A-Za-z0-9._-]{1,64}$' then
    raise exception 'invalid bot id';
  end if;
  if p_captured_at is null or p_snapshot is null or pg_catalog.jsonb_typeof(p_snapshot) <> 'object' then
    raise exception 'invalid trade snapshot';
  end if;

  -- 1. Upsert fleet-wide snapshot
  insert into public.vortext_trade_snapshots as current_row
    (bot_id, captured_at, snapshot, created_at, updated_at)
  values (p_bot_id, p_captured_at, p_snapshot, pg_catalog.now(), pg_catalog.now())
  on conflict (bot_id) do update
    set captured_at = excluded.captured_at,
        snapshot = excluded.snapshot,
        updated_at = pg_catalog.now()
    where current_row.captured_at < excluded.captured_at
  returning true into v_accepted;

  if coalesce(v_accepted, false) and (p_snapshot ? 'accounts') and pg_catalog.jsonb_typeof(p_snapshot->'accounts') = 'array' then
    -- 2. Upsert per-account snapshots
    for v_acct in select * from pg_catalog.jsonb_array_elements(p_snapshot->'accounts') loop
      insert into public.vortext_account_snapshots as curr_acct
        (bot_id, account_id, login, server, currency, balance, equity, margin, free_margin, trade_mode, captured_at, snapshot, created_at, updated_at)
      values (
        p_bot_id,
        v_acct->>'account_id',
        coalesce((v_acct->>'login')::bigint, 0),
        coalesce(v_acct->>'server', ''),
        coalesce(v_acct->>'currency', 'USD'),
        coalesce((v_acct->>'balance')::numeric, 0),
        coalesce((v_acct->>'equity')::numeric, 0),
        coalesce((v_acct->>'margin')::numeric, 0),
        coalesce((v_acct->>'free_margin')::numeric, 0),
        coalesce(v_acct->>'trade_mode', 'DEMO'),
        p_captured_at,
        v_acct,
        pg_catalog.now(),
        pg_catalog.now()
      )
      on conflict (bot_id, account_id) do update
        set login = excluded.login,
            server = excluded.server,
            currency = excluded.currency,
            balance = excluded.balance,
            equity = excluded.equity,
            margin = excluded.margin,
            free_margin = excluded.free_margin,
            trade_mode = excluded.trade_mode,
            captured_at = excluded.captured_at,
            snapshot = excluded.snapshot,
            updated_at = pg_catalog.now()
        where curr_acct.captured_at < excluded.captured_at;
    end loop;
  end if;

  return pg_catalog.jsonb_build_object('accepted', coalesce(v_accepted, false));
end;
$$;

revoke all on function public.upsert_vortext_multi_account_snapshot(text, timestamptz, jsonb) from public, anon, authenticated;
grant execute on function public.upsert_vortext_multi_account_snapshot(text, timestamptz, jsonb) to service_role;
