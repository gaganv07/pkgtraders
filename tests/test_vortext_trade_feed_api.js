'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { Readable } = require('node:stream');
const handler = require('../website/api/trades.js');

const USER_ID = '550e8400-e29b-41d4-a716-446655440000';
const EMAIL = 'owner@example.com';
const BASE_ENV = {
  SUPABASE_URL: 'https://xtyszeuvtfcgognkrwxv.supabase.co',
  SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_test',
  SUPABASE_SECRET_KEY: 'sb_secret_test',
  VORTEXT_BOT_HMAC_SECRET: 'h'.repeat(64),
  VORTEXT_BOT_ID: 'vortext-fleet'
};
const ENV_KEYS = [...Object.keys(BASE_ENV), 'VORTEXT_DASHBOARD_ALLOWED_EMAILS'];

function makeSnapshot(overrides = {}) {
  const now = new Date().toISOString();
  const accounts = [
    {
      account_id: 'mt5-A', login: 10101, server: 'Broker-A', currency: 'USD',
      balance: 1000, equity: 1010, margin: 10, free_margin: 1000,
      leverage: 100, trade_mode: 'DEMO', positions_count: 1, deals_count: 1
    },
    {
      account_id: 'mt5-B', login: 20202, server: 'Broker-B', currency: 'EUR',
      balance: 2000, equity: 1990, margin: 20, free_margin: 1970,
      leverage: 100, trade_mode: 'REAL', positions_count: 1, deals_count: 1
    }
  ];
  return {
    bot_id: 'vortext-fleet',
    captured_at: now,
    account: {
      server: 'Fleet (2 accounts)', currency: 'USD', balance: 3000, equity: 3000,
      margin: 30, free_margin: 2970, leverage: 100, trade_mode: 'UNKNOWN'
    },
    accounts,
    positions: [
      {
        account_id: 'mt5-A', ticket: 'A-1', symbol: 'XAUUSD', side: 'buy',
        volume: 0.01, entry_price: 2000, current_price: 2001, sl: 0, tp: 0,
        profit: 1, swap: 0
      },
      {
        account_id: 'mt5-B', ticket: 'B-1', symbol: 'EURUSD', side: 'sell',
        volume: 0.02, entry_price: 1.1, current_price: 1.09, sl: 0, tp: 0,
        profit: 2, swap: 0
      }
    ],
    deals: [
      {
        account_id: 'mt5-A', ticket: 'A-D1', symbol: 'XAUUSD', side: 'buy',
        entry: 'out', volume: 0.01, price: 2001, profit: 1, commission: 0,
        swap: 0, fee: 0, net_profit: 1, time: now
      },
      {
        account_id: 'mt5-B', ticket: 'B-D1', symbol: 'EURUSD', side: 'sell',
        entry: 'out', volume: 0.02, price: 1.09, profit: 2, commission: 0,
        swap: 0, fee: 0, net_profit: 2, time: now
      }
    ],
    bot_status: 'running',
    ...overrides
  };
}

function makeResponse(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' }
  });
}

function makeRes() {
  return {
    statusCode: 200,
    headers: {},
    body: '',
    setHeader(name, value) { this.headers[name.toLowerCase()] = value; },
    end(value) { this.body = value; }
  };
}

async function invokeGet({ allowedAccounts = ['mt5-A'], active = true, query = '', allowlist } = {}) {
  const savedEnv = Object.fromEntries(ENV_KEYS.map(key => [key, process.env[key]]));
  const previousFetch = global.fetch;
  const calls = [];
  try {
    Object.assign(process.env, BASE_ENV);
    delete process.env.VORTEXT_DASHBOARD_ALLOWED_EMAILS;
    if (allowlist !== undefined) process.env.VORTEXT_DASHBOARD_ALLOWED_EMAILS = allowlist;

    const operator = {
      user_id: USER_ID,
      email: EMAIL,
      role: 'SUPER_ADMIN',
      allowed_accounts: allowedAccounts,
      is_active: active
    };
    const snapshot = makeSnapshot();
    global.fetch = async function (url, options = {}) {
      const parsed = new URL(url);
      calls.push({ path: parsed.pathname, method: options.method || 'GET' });
      if (parsed.pathname.endsWith('/auth/v1/user')) {
        return makeResponse(200, { id: USER_ID, email: EMAIL });
      }
      if (parsed.pathname.endsWith('/rest/v1/vortext_authorized_operators')) {
        return makeResponse(200, active ? [operator] : [{ ...operator, is_active: false }]);
      }
      if (parsed.pathname.endsWith('/rest/v1/vortext_trade_snapshots')) {
        return makeResponse(200, [{
          bot_id: 'vortext-fleet',
          captured_at: snapshot.captured_at,
          updated_at: snapshot.captured_at,
          snapshot
        }]);
      }
      throw new Error('Unexpected upstream request: ' + parsed.pathname);
    };

    const req = {
      method: 'GET',
      headers: { authorization: 'Bearer valid-test-session' },
      url: '/api/trades' + query
    };
    const res = makeRes();
    await handler(req, res);
    return {
      status: res.statusCode,
      body: JSON.parse(res.body || '{}'),
      calls
    };
  } finally {
    global.fetch = previousFetch;
    for (const key of ENV_KEYS) {
      if (savedEnv[key] === undefined) delete process.env[key];
      else process.env[key] = savedEnv[key];
    }
  }
}

test('GET returns only the signed-in operator assigned account data', async () => {
  const result = await invokeGet({ allowedAccounts: ['mt5-A'] });
  assert.equal(result.status, 200);
  assert.equal(result.body.snapshot.accounts.length, 1);
  assert.equal(result.body.snapshot.accounts[0].account_id, 'mt5-A');
  assert.deepEqual(result.body.snapshot.positions.map(row => row.account_id), ['mt5-A']);
  assert.deepEqual(result.body.snapshot.deals.map(row => row.account_id), ['mt5-A']);
  assert.deepEqual(result.body.authorized_account_ids, ['mt5-A']);
});

test('GET rejects a guessed account_id that is not assigned to the user', async () => {
  const result = await invokeGet({ allowedAccounts: ['mt5-A'], query: '?account_id=mt5-B' });
  assert.equal(result.status, 403);
  assert.equal(result.body.snapshot, undefined);
  assert.equal(result.calls.some(call => call.path.endsWith('/rest/v1/vortext_trade_snapshots')), false);
});

test('GET rejects inactive operator grants', async () => {
  const result = await invokeGet({ allowedAccounts: ['mt5-A'], active: false });
  assert.equal(result.status, 403);
});

test('GET treats the email allowlist as an additional restriction', async () => {
  const result = await invokeGet({
    allowedAccounts: ['mt5-A'],
    allowlist: 'different-user@example.com'
  });
  assert.equal(result.status, 403);
  assert.equal(result.calls.some(call => call.path.endsWith('/rest/v1/vortext_authorized_operators')), false);
});

test('GET does not sum balances across different account currencies', async () => {
  const result = await invokeGet({ allowedAccounts: ['mt5-A', 'mt5-B'] });
  assert.equal(result.status, 200);
  assert.equal(result.body.snapshot.account.currency, 'MULTI');
  assert.equal(result.body.snapshot.account.balance, null);
  assert.deepEqual(
    result.body.snapshot.accounts.map(row => row.account_id).sort(),
    ['mt5-A', 'mt5-B']
  );
});

test('GET requires a bearer session before reading any private data', async () => {
  const savedEnv = Object.fromEntries(ENV_KEYS.map(key => [key, process.env[key]]));
  const previousFetch = global.fetch;
  let upstreamCalls = 0;
  try {
    Object.assign(process.env, BASE_ENV);
    delete process.env.VORTEXT_DASHBOARD_ALLOWED_EMAILS;
    global.fetch = async () => { upstreamCalls += 1; return makeResponse(200, {}); };
    const req = { method: 'GET', headers: {}, url: '/api/trades' };
    const res = makeRes();
    await handler(req, res);
    assert.equal(res.statusCode, 401);
    assert.equal(upstreamCalls, 0);
  } finally {
    global.fetch = previousFetch;
    for (const key of ENV_KEYS) {
      if (savedEnv[key] === undefined) delete process.env[key];
      else process.env[key] = savedEnv[key];
    }
  }
});

test('POST falls back to the base snapshot RPC only when the multi-account RPC is absent', async () => {
  const savedEnv = Object.fromEntries(ENV_KEYS.map(key => [key, process.env[key]]));
  const previousFetch = global.fetch;
  const calls = [];
  try {
    Object.assign(process.env, BASE_ENV);
    const body = JSON.stringify({
      bot_id: 'vortext-fleet',
      captured_at: new Date().toISOString(),
      account: {
        server: 'Broker-A', currency: 'USD', balance: 1000, equity: 1000,
        margin: 0, free_margin: 1000, leverage: 100, trade_mode: 'DEMO'
      },
      accounts: [{
        account_id: 'mt5-A', login: 10101, server: 'Broker-A', currency: 'USD',
        balance: 1000, equity: 1000, margin: 0, free_margin: 1000, leverage: 100,
        trade_mode: 'DEMO', enabled: true, trading_enabled: true,
        positions_count: 0, deals_count: 0
      }],
      positions: [],
      deals: [],
      bot_status: 'running'
    });
    const timestamp = String(Math.floor(Date.now() / 1000));
    const signature = crypto.createHmac('sha256', BASE_ENV.VORTEXT_BOT_HMAC_SECRET)
      .update(timestamp, 'ascii').update('.', 'ascii').update(Buffer.from(body)).digest('hex');

    global.fetch = async function (url, options = {}) {
      const parsed = new URL(url);
      calls.push({ path: parsed.pathname, method: options.method || 'GET' });
      if (parsed.pathname.endsWith('/rpc/upsert_vortext_multi_account_snapshot')) {
        return makeResponse(404, { message: 'function missing' });
      }
      if (parsed.pathname.endsWith('/rpc/upsert_vortext_trade_snapshot')) {
        return makeResponse(200, { accepted: true });
      }
      throw new Error('Unexpected upstream request: ' + parsed.pathname);
    };

    const req = Readable.from([Buffer.from(body)]);
    req.method = 'POST';
    req.headers = {
      'content-type': 'application/json',
      'x-vortext-timestamp': timestamp,
      'x-vortext-signature': signature
    };
    req.url = '/api/trades';
    const res = makeRes();
    await handler(req, res);
    assert.equal(res.statusCode, 200);
    assert.equal(JSON.parse(res.body).ok, true);
    assert.deepEqual(calls.map(call => call.path), [
      '/rest/v1/rpc/upsert_vortext_multi_account_snapshot',
      '/rest/v1/rpc/upsert_vortext_trade_snapshot'
    ]);
  } finally {
    global.fetch = previousFetch;
    for (const key of ENV_KEYS) {
      if (savedEnv[key] === undefined) delete process.env[key];
      else process.env[key] = savedEnv[key];
    }
  }
});
