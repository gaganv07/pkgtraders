const crypto = require('node:crypto');

const BODY_LIMIT = 512 * 1024;
const MAX_CLOCK_SKEW_SECONDS = 300;
const STALE_AFTER_MS = 30000;
const ACCOUNT_ID_PATTERN = /^[A-Za-z0-9._-]{1,40}$/;

function reply(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store, max-age=0');
  res.setHeader('Vary', 'Authorization');
  res.end(JSON.stringify(body));
}

function config() {
  const url = (process.env.SUPABASE_URL || '').replace(/\/+$/, '');
  const publishableKey = process.env.SUPABASE_PUBLISHABLE_KEY || '';
  const secretKey = process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY || '';
  const secret = process.env.VORTEXT_BOT_HMAC_SECRET || '';
  // Keep this aligned with app.vortext_dashboard.VortextDashboardPublisher.
  const botId = (process.env.VORTEXT_BOT_ID || 'vortext-fleet').trim();
  // Optional email fence; leave unset when all signed-in users should see shared feeds.
  const allowedEmails = (process.env.VORTEXT_DASHBOARD_ALLOWED_EMAILS || '')
    .split(',').map(function (s) { return s.trim().toLowerCase(); }).filter(Boolean);
  // Server-controlled shared accounts are visible to every valid Supabase Auth user.
  const sharedAccountIds = [...new Set((process.env.VORTEXT_DASHBOARD_SHARED_ACCOUNTS || '')
    .split(',').map(function (s) { return s.trim(); })
    .filter(function (id) { return ACCOUNT_ID_PATTERN.test(id); }))];
  let validUrl = false;
  try {
    const parsed = new URL(url);
    validUrl = parsed.protocol === 'https:' &&
      (parsed.hostname.endsWith('.supabase.co') || parsed.hostname.endsWith('.supabase.in'));
  } catch (_) {}
  return { url, publishableKey, secretKey, secret, botId, allowedEmails, sharedAccountIds, validUrl };
}

function readyForIngest(c) {
  return c.validUrl && !!c.secretKey && c.secret.length >= 32 &&
    /^[A-Za-z0-9._-]{1,64}$/.test(c.botId);
}
function readyForRead(c) {
  return readyForIngest(c) && !!c.publishableKey;
}

async function readRawBody(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > BODY_LIMIT) {
      const error = new Error('Payload too large');
      error.statusCode = 413;
      throw error;
    }
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks);
}

function validSignature(secret, timestamp, raw, signature) {
  if (!/^[0-9]{10}$/.test(timestamp) || !/^[a-f0-9]{64}$/i.test(signature)) return false;
  const seconds = Number(timestamp);
  if (!Number.isSafeInteger(seconds) ||
      Math.abs(Math.floor(Date.now() / 1000) - seconds) > MAX_CLOCK_SKEW_SECONDS) return false;
  const expected = crypto.createHmac('sha256', secret)
    .update(timestamp, 'ascii').update('.', 'ascii').update(raw).digest();
  const actual = Buffer.from(signature, 'hex');
  return actual.length === expected.length && crypto.timingSafeEqual(actual, expected);
}

function str(value, name, max, required) {
  if (value === undefined || value === null) {
    if (required) throw new Error('Missing field: ' + name);
    return '';
  }
  const result = String(value).trim();
  if ((required && !result) || result.length > max) throw new Error('Invalid field: ' + name);
  return result;
}

function num(value, name, min, max) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < min || parsed > max) {
    throw new Error('Invalid numeric field: ' + name);
  }
  return parsed;
}

function iso(value, name, required) {
  if (value === undefined || value === null || value === '') {
    if (required) throw new Error('Missing field: ' + name);
    return null;
  }
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) throw new Error('Invalid timestamp: ' + name);
  return parsed.toISOString();
}

function normalize(input, c) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('Invalid snapshot');

  const botId = str(input.bot_id, 'bot_id', 64, true);
  if (botId !== c.botId || !/^[A-Za-z0-9._-]{1,64}$/.test(botId)) {
    const error = new Error('Unknown bot ID');
    error.statusCode = 403;
    throw error;
  }

  const capturedAt = iso(input.captured_at, 'captured_at', true);
  const capturedMs = new Date(capturedAt).getTime();
  if (capturedMs > Date.now() + 60000 || capturedMs < Date.now() - 86400000) {
    throw new Error('Snapshot timestamp is outside the accepted range');
  }

  const rawAccount = input.account;
  if (!rawAccount || typeof rawAccount !== 'object' || Array.isArray(rawAccount)) {
    throw new Error('Invalid account snapshot');
  }
  const topMode = str(rawAccount.trade_mode, 'trade_mode', 12, true);
  const topCurrency = str(rawAccount.currency, 'currency', 12, true);
  if (!['DEMO', 'CONTEST', 'REAL', 'UNKNOWN'].includes(topMode) ||
      !/^[A-Za-z0-9]{3,12}$/.test(topCurrency)) {
    throw new Error('Invalid account fields');
  }

  const rawAccounts = Array.isArray(input.accounts) ? input.accounts : [{
    account_id: rawAccount.account_id || 'primary',
    login: rawAccount.login || 0,
    server: rawAccount.server || '',
    currency: topCurrency,
    balance: rawAccount.balance,
    equity: rawAccount.equity,
    margin: rawAccount.margin,
    free_margin: rawAccount.free_margin,
    leverage: rawAccount.leverage,
    trade_mode: topMode,
    enabled: true,
    trading_enabled: true,
    positions_count: Array.isArray(input.positions) ? input.positions.length : 0,
    deals_count: Array.isArray(input.deals) ? input.deals.length : 0
  }];
  if (rawAccounts.length < 1 || rawAccounts.length > 50) throw new Error('Invalid accounts');

  const seenAccounts = new Set();
  const accounts = rawAccounts.map(function (item) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) throw new Error('Invalid account item');
    const accountId = str(item.account_id, 'account.account_id', 40, true);
    if (!ACCOUNT_ID_PATTERN.test(accountId) || seenAccounts.has(accountId)) {
      throw new Error('Invalid or duplicate account ID');
    }
    seenAccounts.add(accountId);

    const currency = str(item.currency || topCurrency, 'account.currency', 12, true);
    const tradeMode = str(item.trade_mode || 'UNKNOWN', 'account.trade_mode', 12, true);
    if (!/^[A-Za-z0-9]{3,12}$/.test(currency) ||
        !['DEMO', 'CONTEST', 'REAL', 'UNKNOWN'].includes(tradeMode)) {
      throw new Error('Invalid account mode or currency');
    }

    return {
      account_id: accountId,
      login: num(item.login === undefined ? 0 : item.login, 'account.login', 0, 1e12),
      server: str(item.server, 'account.server', 100, false),
      currency,
      balance: num(item.balance, 'account.balance', 0, 1e12),
      equity: num(item.equity, 'account.equity', 0, 1e12),
      margin: num(item.margin, 'account.margin', 0, 1e12),
      free_margin: num(item.free_margin, 'account.free_margin', 0, 1e12),
      leverage: num(item.leverage, 'account.leverage', 0, 1e6),
      trade_mode: tradeMode,
      enabled: item.enabled !== false,
      trading_enabled: item.trading_enabled === true,
      positions_count: num(item.positions_count === undefined ? 0 : item.positions_count, 'account.positions_count', 0, 10000),
      deals_count: num(item.deals_count === undefined ? 0 : item.deals_count, 'account.deals_count', 0, 10000)
    };
  });

  if (!Array.isArray(input.positions) || input.positions.length > 500) throw new Error('Invalid positions');
  const positions = input.positions.map(function (item) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) throw new Error('Invalid position');
    const side = str(item.side, 'position.side', 8, true);
    const accountId = str(item.account_id, 'position.account_id',
      40, accounts.length > 1 || item.account_id !== undefined);
    const resolvedAccountId = accountId || (accounts.length === 1 ? accounts[0].account_id : '');
    if (!['buy', 'sell'].includes(side) || !seenAccounts.has(resolvedAccountId)) {
      throw new Error('Invalid position side or account');
    }
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
      account_id: resolvedAccountId,
      login: item.login !== undefined ? num(item.login, 'position.login', 0, 1e12) : 0,
      server: str(item.server, 'position.server', 100, false)
    };
  });

  if (!Array.isArray(input.deals) || input.deals.length > 200) throw new Error('Invalid deals');
  const deals = input.deals.map(function (item) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) throw new Error('Invalid deal');
    const side = str(item.side, 'deal.side', 8, true);
    const entry = str(item.entry, 'deal.entry', 8, true);
    const accountId = str(item.account_id, 'deal.account_id',
      40, accounts.length > 1 || item.account_id !== undefined);
    const resolvedAccountId = accountId || (accounts.length === 1 ? accounts[0].account_id : '');
    if (!['buy', 'sell'].includes(side) ||
        !['in', 'out', 'inout', 'out_by', 'other'].includes(entry) ||
        !seenAccounts.has(resolvedAccountId)) {
      throw new Error('Invalid deal or account');
    }
    const profit = num(item.profit, 'deal.profit', -1e12, 1e12);
    const commission = num(item.commission, 'deal.commission', -1e12, 1e12);
    const swap = num(item.swap, 'deal.swap', -1e12, 1e12);
    const fee = num(item.fee, 'deal.fee', -1e12, 1e12);
    return {
      ticket: str(item.ticket, 'deal.ticket', 40, true),
      position_id: str(item.position_id, 'deal.position_id', 40, false),
      symbol: str(item.symbol, 'deal.symbol', 32, true),
      side,
      entry,
      volume: num(item.volume, 'deal.volume', 0, 1e6),
      price: num(item.price, 'deal.price', 0, 1e12),
      profit,
      commission,
      swap,
      fee,
      net_profit: num(item.net_profit, 'deal.net_profit', -4e12, 4e12),
      time: iso(item.time, 'deal.time', false),
      reason: str(item.reason, 'deal.reason', 24, false),
      magic: str(item.magic, 'deal.magic', 32, false),
      account_id: resolvedAccountId,
      login: item.login !== undefined ? num(item.login, 'deal.login', 0, 1e12) : 0,
      server: str(item.server, 'deal.server', 100, false)
    };
  });

  return {
    bot_id: botId,
    captured_at: capturedAt,
    account: {
      server: str(rawAccount.server, 'account.server', 100, false),
      currency: topCurrency,
      balance: num(rawAccount.balance, 'account.balance', 0, 1e12),
      equity: num(rawAccount.equity, 'account.equity', 0, 1e12),
      margin: num(rawAccount.margin, 'account.margin', 0, 1e12),
      free_margin: num(rawAccount.free_margin, 'account.free_margin', 0, 1e12),
      leverage: num(rawAccount.leverage, 'account.leverage', 0, 1e6),
      trade_mode: topMode
    },
    accounts,
    positions,
    deals,
    bot_status: input.bot_status === 'running' ? 'running' : 'unknown'
  };
}

async function getUser(c, token) {
  const response = await fetch(c.url + '/auth/v1/user', {
    headers: { apikey: c.publishableKey, Authorization: 'Bearer ' + token },
    signal: AbortSignal.timeout(6000),
    cache: 'no-store'
  });
  if (response.status === 401 || response.status === 403) return null;
  if (!response.ok) throw new Error('Authentication service unavailable');
  return response.json();
}

function serviceApiHeaders(c, extra) {
  const headers = Object.assign({ apikey: c.secretKey, Accept: 'application/json' }, extra || {});
  // Supabase REST requires the service key in both apikey and Bearer authorization headers.
  headers.Authorization = 'Bearer ' + c.secretKey;
  return headers;
}

async function getOperatorAccess(c, user) {
  const query = new URLSearchParams({
    select: 'user_id,email,role,allowed_accounts,is_active',
    user_id: 'eq.' + user.id,
    limit: '1'
  });
  const response = await fetch(c.url + '/rest/v1/vortext_authorized_operators?' + query, {
    headers: serviceApiHeaders(c),
    signal: AbortSignal.timeout(6000),
    cache: 'no-store'
  });
  if (!response.ok) throw new Error('Operator access store unavailable');

  const rows = await response.json();
  const operator = Array.isArray(rows) ? rows[0] : null;

  // No operator row is acceptable only when a shared account is configured.
  // An explicitly inactive or mismatched operator record always revokes access.
  if (!operator) return { allowedAccountIds: [], role: 'viewer', denied: false };
  if (operator.is_active !== true ||
      String(operator.user_id || '').toLowerCase() !== String(user.id || '').toLowerCase() ||
      String(operator.email || '').trim().toLowerCase() !== String(user.email || '').trim().toLowerCase()) {
    return { allowedAccountIds: [], role: 'viewer', denied: true };
  }

  const rawAllowed = Array.isArray(operator.allowed_accounts) ? operator.allowed_accounts : [];
  const allowedAccountIds = [...new Set(rawAllowed.map(function (item) {
    return typeof item === 'string' ? item.trim() : '';
  }).filter(function (item) {
    return ACCOUNT_ID_PATTERN.test(item);
  }))];

  return { allowedAccountIds, role: String(operator.role || 'viewer').toLowerCase(), denied: false };
}

async function getLatest(c) {
  const query = new URLSearchParams({
    select: 'bot_id,captured_at,snapshot,updated_at',
    bot_id: 'eq.' + c.botId,
    limit: '1'
  });
  const response = await fetch(c.url + '/rest/v1/vortext_trade_snapshots?' + query, {
    headers: serviceApiHeaders(c),
    signal: AbortSignal.timeout(6000),
    cache: 'no-store'
  });
  if (!response.ok) throw new Error('Trade snapshot storage unavailable');
  const rows = await response.json();
  return Array.isArray(rows) && rows.length ? rows[0] : null;
}

function aggregateVisibleSnapshot(snapshot, visibleAccounts, visiblePositions, visibleDeals) {
  const currencies = [...new Set(visibleAccounts.map(function (item) { return item.currency; }))];
  const modes = [...new Set(visibleAccounts.map(function (item) { return item.trade_mode; }))];
  const sameCurrency = currencies.length === 1;
  const floating = visiblePositions.reduce(function (sum, item) {
    return sum + item.profit + item.swap;
  }, 0);

  let account;
  if (visibleAccounts.length === 1) {
    account = visibleAccounts[0];
  } else {
    account = {
      server: 'All authorized accounts (' + visibleAccounts.length + ')',
      currency: sameCurrency ? currencies[0] : 'MULTI',
      balance: sameCurrency ? visibleAccounts.reduce((sum, item) => sum + item.balance, 0) : null,
      equity: sameCurrency ? visibleAccounts.reduce((sum, item) => sum + item.equity, 0) : null,
      margin: sameCurrency ? visibleAccounts.reduce((sum, item) => sum + item.margin, 0) : null,
      free_margin: sameCurrency ? visibleAccounts.reduce((sum, item) => sum + item.free_margin, 0) : null,
      leverage: null,
      trade_mode: modes.length === 1 ? modes[0] : 'UNKNOWN',
      total_accounts: visibleAccounts.length
    };
    if (!sameCurrency) account.floating_pnl = null;
    else account.floating_pnl = floating;
  }

  const fleetSummary = {
    total_accounts: visibleAccounts.length,
    total_balance: sameCurrency ? account.balance : null,
    total_equity: sameCurrency ? account.equity : null,
    total_floating_pnl: sameCurrency ? floating : null,
    total_positions: visiblePositions.length,
    total_recent_deals: visibleDeals.length
  };

  return Object.assign({}, snapshot, {
    account,
    accounts: visibleAccounts,
    positions: visiblePositions,
    deals: visibleDeals,
    fleet_summary: fleetSummary
  });
}

async function post(req, res, c) {
  if (!readyForIngest(c)) {
    return reply(res, 503, { ok: false, error: 'Trade feed backend is not configured' });
  }
  if (!String(req.headers['content-type'] || '').toLowerCase().includes('application/json')) {
    return reply(res, 415, { ok: false, error: 'Content-Type must be application/json' });
  }

  let raw;
  try {
    raw = await readRawBody(req);
  } catch (error) {
    return reply(res, error.statusCode || 400, {
      ok: false,
      error: error.statusCode === 413 ? 'Payload too large' : 'Could not read request body'
    });
  }

  if (!validSignature(
    c.secret,
    String(req.headers['x-vortext-timestamp'] || ''),
    raw,
    String(req.headers['x-vortext-signature'] || '')
  )) {
    return reply(res, 401, { ok: false, error: 'Invalid or expired bot signature' });
  }

  let snapshot;
  try {
    snapshot = normalize(JSON.parse(raw.toString('utf8')), c);
  } catch (error) {
    return reply(res, error.statusCode || 400, { ok: false, error: error.message || 'Invalid snapshot' });
  }

  try {
    let response = await fetch(c.url + '/rest/v1/rpc/upsert_vortext_multi_account_snapshot', {
      method: 'POST',
      headers: serviceApiHeaders(c, { 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        p_bot_id: snapshot.bot_id,
        p_captured_at: snapshot.captured_at,
        p_snapshot: snapshot
      }),
      signal: AbortSignal.timeout(7000),
      cache: 'no-store'
    });

    // A fresh single-account install may expose only the base snapshot RPC.
    // The JSONB payload is identical; account-level reads remain scoped below.
    if (!response.ok && response.status === 404) {
      response = await fetch(c.url + '/rest/v1/rpc/upsert_vortext_trade_snapshot', {
        method: 'POST',
        headers: serviceApiHeaders(c, { 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          p_bot_id: snapshot.bot_id,
          p_captured_at: snapshot.captured_at,
          p_snapshot: snapshot
        }),
        signal: AbortSignal.timeout(7000),
        cache: 'no-store'
      });
    }

    if (!response.ok) {
      return reply(res, 503, { ok: false, error: 'Trade feed storage is unavailable or not initialized' });
    }

    const savedPayload = await response.json();
    const saved = Array.isArray(savedPayload) ? savedPayload[0] : savedPayload;
    if (!saved || saved.accepted !== true) {
      return reply(res, 409, { ok: false, error: 'Out-of-order snapshot rejected' });
    }
    return reply(res, 200, { ok: true, captured_at: snapshot.captured_at });
  } catch (_) {
    return reply(res, 503, { ok: false, error: 'Trade feed storage is unavailable' });
  }
}

async function get(req, res, c) {
  if (!readyForRead(c)) {
    return reply(res, 503, { ok: false, error: 'Trade feed backend is not configured' });
  }

  const match = String(req.headers.authorization || '').match(/^Bearer\s+([^\s]+)$/i);
  if (!match) return reply(res, 401, { ok: false, error: 'Sign-in required' });

  let user;
  try {
    user = await getUser(c, match[1]);
  } catch (_) {
    return reply(res, 503, { ok: false, error: 'Authentication service is unavailable' });
  }
  if (!user || !user.id || !user.email) {
    return reply(res, 401, { ok: false, error: 'Session is invalid or expired' });
  }

  const email = String(user.email).trim().toLowerCase();
  if (c.allowedEmails.length && !c.allowedEmails.includes(email)) {
    return reply(res, 403, { ok: false, error: 'Account is not authorized to view trading data' });
  }

  let operatorAccess;
  try {
    operatorAccess = await getOperatorAccess(c, user);
  } catch (_) {
    return reply(res, 503, { ok: false, error: 'Account authorization service is unavailable' });
  }
  if (operatorAccess.denied) {
    return reply(res, 403, { ok: false, error: 'This VORTEXT account has been disabled' });
  }

  // Shared feeds are read-only and apply to every valid signed-in user.
  // Per-user operator grants can add accounts but cannot widen the shared list.
  const allowedAccountIds = [...new Set([
    ...c.sharedAccountIds,
    ...operatorAccess.allowedAccountIds
  ])];
  if (!allowedAccountIds.length) {
    return reply(res, 403, { ok: false, error: 'No shared or individually assigned trading-account access is configured' });
  }
  operatorAccess = Object.assign({}, operatorAccess, { allowedAccountIds });

  const parsedUrl = new URL(req.url, 'http://localhost');
  const targetAccountId = parsedUrl.searchParams.get('account_id');
  if (targetAccountId && !operatorAccess.allowedAccountIds.includes(targetAccountId)) {
    return reply(res, 403, { ok: false, error: 'This trading account is not assigned or shared for your user' });
  }

  try {
    const row = await getLatest(c);
    if (!row) {
      return reply(res, 200, {
        ok: true,
        connected: false,
        stale: true,
        bot_id: c.botId,
        authorized_account_ids: operatorAccess.allowedAccountIds,
        authorized_accounts: [],
        snapshot: null
      });
    }

    const rawSnapshot = typeof row.snapshot === 'string' ? JSON.parse(row.snapshot) : row.snapshot;
    if (!rawSnapshot || typeof rawSnapshot !== 'object' || Array.isArray(rawSnapshot)) {
      throw new Error('Invalid stored snapshot');
    }

    const capturedAt = row.captured_at || rawSnapshot.captured_at;
    const capturedMs = new Date(capturedAt).getTime();
    const stale = !Number.isFinite(capturedMs) ||
      Date.now() - capturedMs > STALE_AFTER_MS ||
      capturedMs > Date.now() + 60000;

    const sourceAccounts = Array.isArray(rawSnapshot.accounts) ? rawSnapshot.accounts : [];
    const visibleAccounts = sourceAccounts.filter(function (item) {
      return item && operatorAccess.allowedAccountIds.includes(String(item.account_id || ''));
    });
    const visibleIds = new Set(visibleAccounts.map(function (item) { return item.account_id; }));

    if (targetAccountId && !visibleIds.has(targetAccountId)) {
      return reply(res, 200, {
        ok: true,
        connected: false,
        stale: true,
        bot_id: row.bot_id,
        captured_at: capturedAt,
        updated_at: row.updated_at,
        authorized_account_ids: operatorAccess.allowedAccountIds,
        authorized_accounts: visibleAccounts,
        snapshot: null
      });
    }

    if (!visibleAccounts.length) {
      return reply(res, 200, {
        ok: true,
        connected: false,
        stale: true,
        bot_id: row.bot_id,
        captured_at: capturedAt,
        updated_at: row.updated_at,
        authorized_account_ids: operatorAccess.allowedAccountIds,
        authorized_accounts: [],
        snapshot: null
      });
    }

    const visiblePositions = (Array.isArray(rawSnapshot.positions) ? rawSnapshot.positions : [])
      .filter(function (item) { return visibleIds.has(String(item.account_id || '')); });
    const visibleDeals = (Array.isArray(rawSnapshot.deals) ? rawSnapshot.deals : [])
      .filter(function (item) { return visibleIds.has(String(item.account_id || '')); });

    const selectedAccounts = targetAccountId
      ? visibleAccounts.filter(function (item) { return item.account_id === targetAccountId; })
      : visibleAccounts;
    const selectedIds = new Set(selectedAccounts.map(function (item) { return item.account_id; }));
    const selectedPositions = visiblePositions.filter(function (item) { return selectedIds.has(item.account_id); });
    const selectedDeals = visibleDeals.filter(function (item) { return selectedIds.has(item.account_id); });
    const filteredSnapshot = aggregateVisibleSnapshot(
      rawSnapshot, selectedAccounts, selectedPositions, selectedDeals
    );

    return reply(res, 200, {
      ok: true,
      connected: !stale,
      stale,
      bot_id: row.bot_id,
      captured_at: capturedAt,
      updated_at: row.updated_at,
      authorized_account_ids: operatorAccess.allowedAccountIds,
      authorized_accounts: visibleAccounts,
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
