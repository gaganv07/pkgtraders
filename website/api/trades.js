const crypto = require('node:crypto');

const BODY_LIMIT = 512 * 1024;
const MAX_CLOCK_SKEW_SECONDS = 300;
const STALE_AFTER_MS = 30000;

function reply(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store, max-age=0');
  res.end(JSON.stringify(body));
}

function config() {
  const url = (process.env.SUPABASE_URL || '').replace(/\/+$/, '');
  const publishableKey = process.env.SUPABASE_PUBLISHABLE_KEY || '';
  // Prefer the modern server-only Supabase secret key. Legacy service_role JWTs remain supported.
  const secretKey = process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY || '';
  const secret = process.env.VORTEXT_BOT_HMAC_SECRET || '';
  const botId = (process.env.VORTEXT_BOT_ID || 'vortext-main').trim();
  const allowedEmails = (process.env.VORTEXT_DASHBOARD_ALLOWED_EMAILS || '')
    .split(',').map(function (s) { return s.trim().toLowerCase(); }).filter(Boolean);
  let validUrl = false;
  try {
    const parsed = new URL(url);
    validUrl = parsed.protocol === 'https:' &&
      (parsed.hostname.endsWith('.supabase.co') || parsed.hostname.endsWith('.supabase.in'));
  } catch (_) {}
  return { url, publishableKey, secretKey, secret, botId, allowedEmails, validUrl };
}

function readyForIngest(c) {
  return c.validUrl && !!c.secretKey && c.secret.length >= 32 &&
    /^[A-Za-z0-9._-]{1,64}$/.test(c.botId);
}
function readyForRead(c) {
  return readyForIngest(c) && !!c.publishableKey && c.allowedEmails.length > 0;
}

async function readRawBody(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > BODY_LIMIT) {
      const e = new Error('Payload too large');
      e.statusCode = 413;
      throw e;
    }
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks);
}

function validSignature(secret, timestamp, raw, signature) {
  if (!/^[0-9]{10}$/.test(timestamp) || !/^[a-f0-9]{64}$/i.test(signature)) return false;
  const seconds = Number(timestamp);
  if (!Number.isSafeInteger(seconds) || Math.abs(Math.floor(Date.now() / 1000) - seconds) > MAX_CLOCK_SKEW_SECONDS) return false;
  const expected = crypto.createHmac('sha256', secret).update(timestamp, 'ascii').update('.', 'ascii').update(raw).digest();
  const actual = Buffer.from(signature, 'hex');
  return actual.length === expected.length && crypto.timingSafeEqual(actual, expected);
}

function str(value, name, max, required) {
  if (value === undefined || value === null) {
    if (required) throw new Error('Missing field: ' + name);
    return '';
  }
  const s = String(value).trim();
  if ((required && !s) || s.length > max) throw new Error('Invalid field: ' + name);
  return s;
}
function num(value, name, min, max) {
  const n = Number(value);
  if (!Number.isFinite(n) || n < min || n > max) throw new Error('Invalid numeric field: ' + name);
  return n;
}
function iso(value, name, required) {
  if (value === undefined || value === null || value === '') {
    if (required) throw new Error('Missing field: ' + name);
    return null;
  }
  const d = new Date(value);
  if (!Number.isFinite(d.getTime())) throw new Error('Invalid timestamp: ' + name);
  return d.toISOString();
}

function normalize(input, c) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('Invalid snapshot');
  const botId = str(input.bot_id, 'bot_id', 64, true);
  if (botId !== c.botId || !/^[A-Za-z0-9._-]{1,64}$/.test(botId)) {
    const e = new Error('Unknown bot ID');
    e.statusCode = 403;
    throw e;
  }
  const capturedAt = iso(input.captured_at, 'captured_at', true);
  const capturedMs = new Date(capturedAt).getTime();
  if (capturedMs > Date.now() + 60000 || capturedMs < Date.now() - 86400000) throw new Error('Snapshot timestamp is outside the accepted range');

  const rawAccount = input.account;
  if (!rawAccount || typeof rawAccount !== 'object' || Array.isArray(rawAccount)) throw new Error('Invalid account snapshot');
  const mode = str(rawAccount.trade_mode, 'trade_mode', 12, true);
  const currency = str(rawAccount.currency, 'currency', 12, true);
  if (!['DEMO', 'CONTEST', 'REAL', 'UNKNOWN'].includes(mode) || !/^[A-Za-z0-9]{3,12}$/.test(currency)) throw new Error('Invalid account fields');

  const account = {
    server: str(rawAccount.server, 'server', 100, false),
    currency,
    balance: num(rawAccount.balance, 'balance', 0, 1e12),
    equity: num(rawAccount.equity, 'equity', 0, 1e12),
    margin: num(rawAccount.margin, 'margin', 0, 1e12),
    free_margin: num(rawAccount.free_margin, 'free_margin', 0, 1e12),
    leverage: num(rawAccount.leverage, 'leverage', 0, 1e6),
    trade_mode: mode,
    total_accounts: rawAccount.total_accounts ? num(rawAccount.total_accounts, 'total_accounts', 1, 100) : 1
  };

  // Optional multi-account fleet array
  let accounts = [];
  if (Array.isArray(input.accounts)) {
    accounts = input.accounts.slice(0, 50).map(function (acct) {
      return {
        account_id: str(acct.account_id, 'account.account_id', 40, true),
        login: num(acct.login, 'account.login', 0, 1e12),
        server: str(acct.server, 'account.server', 100, false),
        currency: str(acct.currency, 'account.currency', 12, true),
        balance: num(acct.balance, 'account.balance', 0, 1e12),
        equity: num(acct.equity, 'account.equity', 0, 1e12),
        margin: num(acct.margin, 'account.margin', 0, 1e12),
        free_margin: num(acct.free_margin, 'account.free_margin', 0, 1e12),
        leverage: num(acct.leverage, 'account.leverage', 0, 1e6),
        trade_mode: str(acct.trade_mode, 'account.trade_mode', 12, false) || 'UNKNOWN',
        enabled: Boolean(acct.enabled),
        trading_enabled: Boolean(acct.trading_enabled),
        positions_count: num(acct.positions_count, 'account.positions_count', 0, 1000),
        deals_count: num(acct.deals_count, 'account.deals_count', 0, 1000)
      };
    });
  }

  if (!Array.isArray(input.positions) || input.positions.length > 500) throw new Error('Invalid positions');
  const positions = input.positions.map(function (item) {
    const side = str(item.side, 'position.side', 8, true);
    if (!['buy', 'sell'].includes(side)) throw new Error('Invalid position side');
    return {
      ticket: str(item.ticket, 'position.ticket', 40, true),
      symbol: str(item.symbol, 'position.symbol', 32, true),
      side,
      volume: num(item.volume, 'position.volume', 0, 1e6),
      entry_price: num(item.entry_price, 'position.entry_price', 0, 1e12),
      current_price: num(item.current_price, 'position.current_price', 0, 1e12),
      sl: num(item.sl, 'position.sl', 0, 1e12),
      tp: num(item.tp, 'position.tp', 0, 1e12),
      profit: num(item.profit, 'position.profit', -1e12, 1e12),
      swap: num(item.swap, 'position.swap', -1e12, 1e12),
      opened_at: iso(item.opened_at, 'position.opened_at', false),
      magic: str(item.magic, 'position.magic', 32, false),
      account_id: str(item.account_id, 'position.account_id', 40, false),
      login: item.login !== undefined ? num(item.login, 'position.login', 0, 1e12) : 0,
      server: str(item.server, 'position.server', 100, false)
    };
  });

  if (!Array.isArray(input.deals) || input.deals.length > 200) throw new Error('Invalid deals');
  const deals = input.deals.map(function (item) {
    const side = str(item.side, 'deal.side', 8, true);
    const entry = str(item.entry, 'deal.entry', 8, true);
    if (!['buy', 'sell'].includes(side) || !['in', 'out', 'inout', 'out_by', 'other'].includes(entry)) throw new Error('Invalid deal');
    const profit = num(item.profit, 'profit', -1e12, 1e12);
    const commission = num(item.commission, 'commission', -1e12, 1e12);
    const swap = num(item.swap, 'swap', -1e12, 1e12);
    const fee = num(item.fee, 'fee', -1e12, 1e12);
    return {
      ticket: str(item.ticket, 'deal.ticket', 40, true),
      position_id: str(item.position_id, 'deal.position_id', 40, false),
      symbol: str(item.symbol, 'deal.symbol', 32, true),
      side, entry,
      volume: num(item.volume, 'deal.volume', 0, 1e6),
      price: num(item.price, 'deal.price', 0, 1e12),
      profit, commission, swap, fee,
      net_profit: num(item.net_profit, 'net_profit', -4e12, 4e12),
      time: iso(item.time, 'deal.time', false),
      reason: str(item.reason, 'deal.reason', 24, false),
      magic: str(item.magic, 'deal.magic', 32, false),
      account_id: str(item.account_id, 'deal.account_id', 40, false),
      login: item.login !== undefined ? num(item.login, 'deal.login', 0, 1e12) : 0,
      server: str(item.server, 'deal.server', 100, false)
    };
  });

  const out = {
    bot_id: botId,
    captured_at: capturedAt,
    account,
    positions,
    deals,
    bot_status: input.bot_status === 'running' ? 'running' : 'unknown'
  };
  if (accounts.length > 0) out.accounts = accounts;
  if (input.fleet_summary && typeof input.fleet_summary === 'object') out.fleet_summary = input.fleet_summary;
  return out;
}

async function getUser(c, token) {
  const response = await fetch(c.url + '/auth/v1/user', {
    headers: { apikey: c.publishableKey, Authorization: 'Bearer ' + token },
    signal: AbortSignal.timeout(6000), cache: 'no-store'
  });
  if (!response.ok) return null;
  return response.json();
}

function serviceApiHeaders(c, extra) {
  const headers = Object.assign({
    apikey: c.secretKey,
    Accept: 'application/json'
  }, extra || {});
  if (c.secretKey.startsWith('eyJ')) headers.Authorization = 'Bearer ' + c.secretKey;
  return headers;
}

async function getLatest(c) {
  const query = new URLSearchParams({ select: 'bot_id,captured_at,snapshot,updated_at', bot_id: 'eq.' + c.botId, limit: '1' });
  const response = await fetch(c.url + '/rest/v1/vortext_trade_snapshots?' + query, {
    headers: serviceApiHeaders(c),
    signal: AbortSignal.timeout(6000), cache: 'no-store'
  });
  if (!response.ok) throw new Error('Storage unavailable');
  const rows = await response.json();
  return Array.isArray(rows) && rows.length ? rows[0] : null;
}

async function post(req, res, c) {
  if (!readyForIngest(c)) return reply(res, 503, { ok: false, error: 'Trade feed backend is not configured' });
  if (!String(req.headers['content-type'] || '').toLowerCase().includes('application/json')) return reply(res, 415, { ok: false, error: 'Content-Type must be application/json' });
  let raw;
  try { raw = await readRawBody(req); }
  catch (e) { return reply(res, e.statusCode || 400, { ok: false, error: e.statusCode === 413 ? 'Payload too large' : 'Could not read request body' }); }
  if (!validSignature(c.secret, String(req.headers['x-vortext-timestamp'] || ''), raw, String(req.headers['x-vortext-signature'] || ''))) {
    return reply(res, 401, { ok: false, error: 'Invalid or expired bot signature' });
  }
  let snapshot;
  try { snapshot = normalize(JSON.parse(raw.toString('utf8')), c); }
  catch (e) { return reply(res, e.statusCode || 400, { ok: false, error: e.message || 'Invalid snapshot' }); }

  try {
    // Attempt multi-account RPC first
    let response = await fetch(c.url + '/rest/v1/rpc/upsert_vortext_multi_account_snapshot', {
      method: 'POST',
      headers: serviceApiHeaders(c, { 'Content-Type': 'application/json' }),
      body: JSON.stringify({ p_bot_id: snapshot.bot_id, p_captured_at: snapshot.captured_at, p_snapshot: snapshot }),
      signal: AbortSignal.timeout(7000), cache: 'no-store'
    });

    // If multi-account RPC is not present (404), fall back to standard snapshot RPC
    if (!response.ok && response.status === 404) {
      response = await fetch(c.url + '/rest/v1/rpc/upsert_vortext_trade_snapshot', {
        method: 'POST',
        headers: serviceApiHeaders(c, { 'Content-Type': 'application/json' }),
        body: JSON.stringify({ p_bot_id: snapshot.bot_id, p_captured_at: snapshot.captured_at, p_snapshot: snapshot }),
        signal: AbortSignal.timeout(7000), cache: 'no-store'
      });
    }

    if (!response.ok) return reply(res, 503, { ok: false, error: 'Trade feed storage is unavailable or not initialized' });
    const saved = await response.json();
    if (!saved || saved.accepted !== true) return reply(res, 409, { ok: false, error: 'Out-of-order snapshot rejected' });
    return reply(res, 200, { ok: true, captured_at: snapshot.captured_at });
  } catch (_) {
    return reply(res, 503, { ok: false, error: 'Trade feed storage is unavailable' });
  }
}

async function get(req, res, c) {
  if (!readyForRead(c)) return reply(res, 503, { ok: false, error: 'Trade feed backend or authorized-email allowlist is not configured' });
  const match = String(req.headers.authorization || '').match(/^Bearer\s+([^\s]+)$/i);
  if (!match) return reply(res, 401, { ok: false, error: 'Sign-in required' });
  let user;
  try { user = await getUser(c, match[1]); }
  catch (_) { return reply(res, 503, { ok: false, error: 'Authentication service is unavailable' }); }
  if (!user || !user.email) return reply(res, 401, { ok: false, error: 'Session is invalid or expired' });
  if (!c.allowedEmails.includes(String(user.email).toLowerCase())) return reply(res, 403, { ok: false, error: 'Account is not authorized to view trading data' });

  try {
    const row = await getLatest(c);
    if (!row) return reply(res, 200, { ok: true, connected: false, stale: true, bot_id: c.botId, snapshot: null });
    const snapshot = typeof row.snapshot === 'string' ? JSON.parse(row.snapshot) : row.snapshot;
    const ms = new Date(row.captured_at || snapshot.captured_at).getTime();
    const stale = !Number.isFinite(ms) || Date.now() - ms > STALE_AFTER_MS || ms > Date.now() + 60000;

    // Optional query parameter filtering by account_id
    let filteredSnapshot = snapshot;
    const parsedUrl = new URL(req.url, 'http://localhost');
    const targetAccountId = parsedUrl.searchParams.get('account_id');
    if (targetAccountId && snapshot && Array.isArray(snapshot.accounts)) {
      const matchedAcct = snapshot.accounts.find(function (a) { return a.account_id === targetAccountId; });
      if (matchedAcct) {
        filteredSnapshot = Object.assign({}, snapshot, {
          account: matchedAcct,
          positions: (snapshot.positions || []).filter(function (p) { return p.account_id === targetAccountId; }),
          deals: (snapshot.deals || []).filter(function (d) { return d.account_id === targetAccountId; })
        });
      }
    }

    return reply(res, 200, {
      ok: true,
      connected: !stale,
      stale,
      bot_id: row.bot_id,
      captured_at: row.captured_at,
      updated_at: row.updated_at,
      snapshot: filteredSnapshot
    });
  } catch (_) {
    return reply(res, 503, { ok: false, error: 'Trade feed storage is unavailable or not initialized' });
  }
}

module.exports = async function handler(req, res) {
  const c = config();
  if (req.method === 'POST') return post(req, res, c);
  if (req.method === 'GET') return get(req, res, c);
  res.setHeader('Allow', 'GET, POST');
  return reply(res, 405, { ok: false, error: 'Method not allowed' });
};
module.exports.config = { api: { bodyParser: false } };
