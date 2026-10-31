/**
 * PKG Traders Central Backend REST API Service
 * Architecture:
 * - Independent central Node.js service
 * - In-memory / relational database layer (Prisma compatible)
 * - Strict tenant isolation for Client Website
 * - Role-Based Access Control (RBAC) & Audit Logging for Admin Website
 * - Outbound HMAC-SHA256 authenticated telemetry ingestion for Trading Bot PC
 */

const http = require('http');
const url = require('url');
const {
  hashPassword,
  verifyPassword,
  generateBotHMACSignature,
  verifyBotHMACSignature,
  signJWT,
  verifyJWT,
  JWT_CLIENT_SECRET,
  JWT_ADMIN_SECRET
} = require('./auth');

const PORT = process.env.PORT || 4000;

// ---------------------------------------------------------
// IN-MEMORY HIGH-PERFORMANCE SECURE DB STORE (PROD: PRISMA / POSTGRES)
// ---------------------------------------------------------
const db = {
  users: [
    {
      id: 'usr-client-001',
      email: 'client@pkgtraders.com',
      passwordHash: hashPassword('ClientPass123!'),
      firstName: 'Gagan',
      lastName: 'Trader',
      isSuspended: false,
      createdAt: new Date().toISOString()
    }
  ],
  adminUsers: [
    {
      id: 'usr-admin-001',
      email: 'admin@pkgtraders.com',
      passwordHash: hashPassword('AdminPass123!'),
      firstName: 'System',
      lastName: 'Administrator',
      roleType: 'SUPER_ADMIN',
      isActive: true,
      createdAt: new Date().toISOString()
    }
  ],
  kycProfiles: [
    {
      id: 'kyc-001',
      userId: 'usr-client-001',
      status: 'APPROVED',
      rejectionReason: null,
      reviewedByAdminId: 'usr-admin-001',
      submittedAt: new Date().toISOString(),
      documents: [
        { id: 'doc-001', type: 'PASSPORT', fileUrl: 'https://storage.pkgtraders.com/kyc/passport_001.pdf', uploadedAt: new Date().toISOString() }
      ]
    }
  ],
  tradingAccounts: [
    {
      id: 'ta-001',
      mt5Login: 26128885,
      accountName: 'Standard Vantage Account 1',
      magicNumber: 20250701,
      currency: 'USD',
      balance: 495.37,
      equity: 483.96,
      margin: 18.56,
      freeMargin: 465.40,
      marginLevel: 2607.54,
      status: 'ACTIVE',
      lastSyncAt: new Date().toISOString()
    },
    {
      id: 'ta-003',
      mt5Login: 26179878,
      accountName: 'Standard Vantage Account 3',
      magicNumber: 20250703,
      currency: 'USD',
      balance: 1000.00,
      equity: 1000.00,
      margin: 0.00,
      freeMargin: 1000.00,
      marginLevel: 0.00,
      status: 'ACTIVE',
      lastSyncAt: new Date().toISOString()
    }
  ],
  accountUserMappings: [
    { id: 'map-001', userId: 'usr-client-001', tradingAccountId: 'ta-001' },
    { id: 'map-002', userId: 'usr-client-001', tradingAccountId: 'ta-003' }
  ],
  openPositions: [],
  trades: [],
  deposits: [
    {
      id: 'dep-001',
      transactionId: 'TXN-DEP-1001',
      userId: 'usr-client-001',
      amount: 500.00,
      currency: 'USD',
      status: 'COMPLETED',
      paymentMethod: 'BANK_WIRE',
      proofUrl: 'https://storage.pkgtraders.com/proofs/dep_1001.pdf',
      createdAt: new Date().toISOString()
    }
  ],
  withdrawals: [
    {
      id: 'wth-001',
      transactionId: 'TXN-WTH-2001',
      userId: 'usr-client-001',
      amount: 50.00,
      currency: 'USD',
      status: 'PENDING',
      destinationAddress: 'US8937000123456789',
      paymentMethod: 'BANK_WIRE',
      createdAt: new Date().toISOString()
    }
  ],
  auditLogs: [
    {
      id: 'aud-001',
      actorAdminId: 'usr-admin-001',
      action: 'SYSTEM_INITIALIZED',
      targetEntity: 'System:Backend',
      ipAddress: '127.0.0.1',
      metadata: JSON.stringify({ version: '2.0.0' }),
      createdAt: new Date().toISOString()
    }
  ],
  botStatus: {
    instanceName: 'TRADING_BOT_PC_01',
    pcHostname: 'TRADING-DESKTOP',
    botVersion: '2.0.0',
    status: 'ONLINE',
    lastHeartbeat: new Date().toISOString(),
    activeAccountCount: 2
  }
};

// Helper to log audit trail
function logAudit(actorAdminId, actorUserId, action, targetEntity, ipAddress, metadata) {
  const entry = {
    id: `aud-${Date.now()}-${Math.floor(Math.random()*1000)}`,
    actorAdminId: actorAdminId || null,
    actorUserId: actorUserId || null,
    action,
    targetEntity,
    ipAddress: ipAddress || '127.0.0.1',
    metadata: typeof metadata === 'object' ? JSON.stringify(metadata) : (metadata || null),
    createdAt: new Date().toISOString()
  };
  db.auditLogs.unshift(entry);
}

// JSON Helper
function sendJSON(res, statusCode, data) {
  res.writeHead(statusCode, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Bot-Api-Key, X-Bot-Timestamp, X-Bot-Signature'
  });
  res.end(JSON.stringify(data));
}

// Read body helper
function parseRequestBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => { body += chunk.toString(); });
    req.on('end', () => {
      if (!body) return resolve({});
      try {
        resolve(JSON.parse(body));
      } catch (err) {
        resolve({ raw: body });
      }
    });
  });
}

// Server Request Handler
const server = http.createServer(async (req, res) => {
  const parsedUrl = url.parse(req.url, true);
  const pathname = parsedUrl.pathname;
  const method = req.method;

  // Handle CORS preflight
  if (method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Bot-Api-Key, X-Bot-Timestamp, X-Bot-Signature'
    });
    return res.end();
  }

  // ---------------------------------------------------------
  // 1. BOT TELEMETRY INGESTION ENDPOINT (HMAC AUTHENTICATED)
  // ---------------------------------------------------------
  if (pathname === '/api/v1/bot/sync' && method === 'POST') {
    const timestampHeader = req.headers['x-bot-timestamp'];
    const signatureHeader = req.headers['x-bot-signature'];
    const rawBody = await new Promise((resolve) => {
      let body = '';
      req.on('data', chunk => body += chunk);
      req.on('end', () => resolve(body));
    });

    const isValidSig = verifyBotHMACSignature(rawBody, timestampHeader, signatureHeader);
    if (!isValidSig) {
      return sendJSON(res, 401, { error: 'UNAUTHORIZED_BOT_SIGNATURE', message: 'Invalid HMAC signature or stale timestamp window.' });
    }

    try {
      const payload = JSON.parse(rawBody);
      db.botStatus = {
        instanceName: payload.instance_name || 'TRADING_BOT_PC_01',
        pcHostname: payload.pc_hostname || 'WINDOWS-PC',
        botVersion: payload.bot_version || '2.0.0',
        status: 'ONLINE',
        lastHeartbeat: new Date().toISOString(),
        activeAccountCount: payload.accounts ? payload.accounts.length : 0
      };

      if (Array.isArray(payload.accounts)) {
        for (const accPayload of payload.accounts) {
          let existingAcc = db.tradingAccounts.find(a => a.mt5Login === accPayload.mt5_login);
          if (existingAcc) {
            existingAcc.balance = accPayload.balance;
            existingAcc.equity = accPayload.equity;
            existingAcc.margin = accPayload.margin;
            existingAcc.freeMargin = accPayload.free_margin;
            existingAcc.marginLevel = accPayload.margin_level;
            existingAcc.lastSyncAt = new Date().toISOString();
          } else {
            existingAcc = {
              id: `ta-${Date.now()}`,
              mt5Login: accPayload.mt5_login,
              accountName: `Account #${accPayload.mt5_login}`,
              magicNumber: accPayload.magic_number,
              currency: 'USD',
              balance: accPayload.balance,
              equity: accPayload.equity,
              margin: accPayload.margin,
              freeMargin: accPayload.free_margin,
              marginLevel: accPayload.margin_level,
              status: 'ACTIVE',
              lastSyncAt: new Date().toISOString()
            };
            db.tradingAccounts.push(existingAcc);
          }

          // Update open positions for this account
          if (Array.isArray(accPayload.open_positions)) {
            db.openPositions = db.openPositions.filter(p => p.tradingAccountId !== existingAcc.id);
            for (const pos of accPayload.open_positions) {
              db.openPositions.push({
                id: `pos-${pos.position_ticket}`,
                tradingAccountId: existingAcc.id,
                positionTicket: pos.position_ticket,
                symbol: pos.symbol,
                direction: pos.direction,
                volume: pos.volume,
                entryPrice: pos.entry_price,
                currentPrice: pos.current_price,
                stopLoss: pos.stop_loss,
                takeProfit: pos.take_profit,
                unrealizedPnL: pos.unrealized_pnl,
                openedAt: pos.opened_at
              });
            }
          }

          // Ingest trades
          if (Array.isArray(accPayload.recent_trades)) {
            for (const tr of accPayload.recent_trades) {
              if (!db.trades.some(t => t.dealTicket === tr.deal_ticket)) {
                db.trades.push({
                  id: `trd-${tr.deal_ticket}`,
                  tradingAccountId: existingAcc.id,
                  dealTicket: tr.deal_ticket,
                  orderTicket: tr.order_ticket,
                  symbol: tr.symbol,
                  direction: tr.direction,
                  volume: tr.volume,
                  entryPrice: tr.entry_price,
                  realizedPnL: tr.realized_pnl,
                  commission: tr.commission,
                  swap: tr.swap,
                  executedAt: tr.executed_at,
                  comment: tr.comment
                });
              }
            }
          }
        }
      }

      return sendJSON(res, 200, { status: 'SUCCESS', message: 'Telemetry snapshot synchronized cleanly.' });
    } catch (err) {
      return sendJSON(res, 400, { error: 'INVALID_PAYLOAD', message: err.message });
    }
  }

  // ---------------------------------------------------------
  // 2. CLIENT AUTHENTICATION ENDPOINTS
  // ---------------------------------------------------------
  if (pathname === '/api/v1/client/auth/login' && method === 'POST') {
    const body = await parseRequestBody(req);
    const user = db.users.find(u => u.email === body.email);
    if (!user || !verifyPassword(body.password, user.passwordHash)) {
      return sendJSON(res, 401, { error: 'INVALID_CREDENTIALS', message: 'Invalid email or password.' });
    }
    if (user.isSuspended) {
      return sendJSON(res, 403, { error: 'ACCOUNT_SUSPENDED', message: 'Your account is suspended. Contact compliance.' });
    }

    const token = signJWT({ userId: user.id, email: user.email, role: 'CLIENT' }, JWT_CLIENT_SECRET);
    return sendJSON(res, 200, {
      token,
      user: { id: user.id, email: user.email, firstName: user.firstName, lastName: user.lastName }
    });
  }

  if (pathname === '/api/v1/client/auth/register' && method === 'POST') {
    const body = await parseRequestBody(req);
    if (!body.email || !body.password || !body.firstName || !body.lastName) {
      return sendJSON(res, 400, { error: 'MISSING_FIELDS', message: 'All fields are required.' });
    }
    if (db.users.some(u => u.email === body.email)) {
      return sendJSON(res, 409, { error: 'EMAIL_EXISTS', message: 'Email address is already registered.' });
    }

    const newUser = {
      id: `usr-client-${Date.now()}`,
      email: body.email,
      passwordHash: hashPassword(body.password),
      firstName: body.firstName,
      lastName: body.lastName,
      isSuspended: false,
      createdAt: new Date().toISOString()
    };
    db.users.push(newUser);

    // Auto create KYC record
    db.kycProfiles.push({
      id: `kyc-${Date.now()}`,
      userId: newUser.id,
      status: 'NOT_SUBMITTED',
      rejectionReason: null,
      submittedAt: null,
      documents: []
    });

    const token = signJWT({ userId: newUser.id, email: newUser.email, role: 'CLIENT' }, JWT_CLIENT_SECRET);
    return sendJSON(res, 201, {
      token,
      user: { id: newUser.id, email: newUser.email, firstName: newUser.firstName, lastName: newUser.lastName }
    });
  }

  // ---------------------------------------------------------
  // 3. ADMIN AUTHENTICATION ENDPOINTS
  // ---------------------------------------------------------
  if (pathname === '/api/v1/admin/auth/login' && method === 'POST') {
    const body = await parseRequestBody(req);
    const admin = db.adminUsers.find(a => a.email === body.email);
    if (!admin || !verifyPassword(body.password, admin.passwordHash)) {
      return sendJSON(res, 401, { error: 'INVALID_CREDENTIALS', message: 'Invalid admin credentials.' });
    }

    logAudit(admin.id, null, 'ADMIN_LOGIN', `Admin:${admin.email}`, req.socket.remoteAddress, { timestamp: new Date().toISOString() });

    const token = signJWT({ adminId: admin.id, email: admin.email, role: admin.roleType }, JWT_ADMIN_SECRET);
    return sendJSON(res, 200, {
      token,
      admin: { id: admin.id, email: admin.email, firstName: admin.firstName, lastName: admin.lastName, role: admin.roleType }
    });
  }

  // ---------------------------------------------------------
  // CLIENT PORTAL PROTECTED ENDPOINTS (TENANT ISOLATED)
  // ---------------------------------------------------------
  if (pathname.startsWith('/api/v1/client/')) {
    const authHeader = req.headers['authorization'];
    const token = authHeader && authHeader.startsWith('Bearer ') ? authHeader.substring(7) : null;
    const payload = verifyJWT(token, JWT_CLIENT_SECRET);
    if (!payload || payload.role !== 'CLIENT') {
      return sendJSON(res, 401, { error: 'UNAUTHORIZED_CLIENT_ACCESS', message: 'Valid client JWT required.' });
    }

    const userId = payload.userId;
    const userObj = db.users.find(u => u.id === userId);
    if (!userObj || userObj.isSuspended) {
      return sendJSON(res, 403, { error: 'SUSPENDED_OR_NOT_FOUND', message: 'Account inaccessible.' });
    }

    // Get mapped trading accounts for this client
    const mappedAccIds = db.accountUserMappings.filter(m => m.userId === userId).map(m => m.tradingAccountId);
    const userAccounts = db.tradingAccounts.filter(a => mappedAccIds.includes(a.id));

    // Dashboard Overview Endpoint
    if (pathname === '/api/v1/client/dashboard' && method === 'GET') {
      const kyc = db.kycProfiles.find(k => k.userId === userId);
      const totalBalance = userAccounts.reduce((sum, a) => sum + (parseFloat(a.balance) || 0), 0);
      const totalEquity = userAccounts.reduce((sum, a) => sum + (parseFloat(a.equity) || 0), 0);
      const openPositions = db.openPositions.filter(p => mappedAccIds.includes(p.tradingAccountId));
      const closedTrades = db.trades.filter(t => mappedAccIds.includes(t.tradingAccountId));
      const clientDeposits = db.deposits.filter(d => d.userId === userId);
      const clientWithdrawals = db.withdrawals.filter(w => w.userId === userId);

      return sendJSON(res, 200, {
        user: { id: userObj.id, email: userObj.email, firstName: userObj.firstName, lastName: userObj.lastName },
        kycStatus: kyc ? kyc.status : 'NOT_SUBMITTED',
        financials: {
          totalBalance,
          totalEquity,
          openPositionsCount: openPositions.length,
          closedTradesCount: closedTrades.length,
          totalDeposited: clientDeposits.filter(d => d.status === 'COMPLETED').reduce((s, d) => s + d.amount, 0),
          totalWithdrawn: clientWithdrawals.filter(w => w.status === 'COMPLETED').reduce((s, w) => s + w.amount, 0)
        },
        accounts: userAccounts,
        openPositions,
        recentTrades: closedTrades.slice(-10)
      });
    }

    // Client KYC Endpoint
    if (pathname === '/api/v1/client/kyc' && method === 'GET') {
      const kyc = db.kycProfiles.find(k => k.userId === userId);
      return sendJSON(res, 200, { kyc });
    }

    if (pathname === '/api/v1/client/kyc/submit' && method === 'POST') {
      const body = await parseRequestBody(req);
      let kyc = db.kycProfiles.find(k => k.userId === userId);
      if (!kyc) {
        kyc = { id: `kyc-${Date.now()}`, userId, status: 'PENDING', submittedAt: new Date().toISOString(), documents: [] };
        db.kycProfiles.push(kyc);
      } else {
        kyc.status = 'PENDING';
        kyc.submittedAt = new Date().toISOString();
      }
      if (body.documentType && body.fileUrl) {
        kyc.documents.push({
          id: `doc-${Date.now()}`,
          type: body.documentType,
          fileUrl: body.fileUrl,
          uploadedAt: new Date().toISOString()
        });
      }
      return sendJSON(res, 200, { message: 'KYC Document submitted successfully for verification.', kyc });
    }

    // Deposits Endpoint
    if (pathname === '/api/v1/client/deposits' && method === 'GET') {
      const deposits = db.deposits.filter(d => d.userId === userId);
      return sendJSON(res, 200, { deposits });
    }

    if (pathname === '/api/v1/client/deposits' && method === 'POST') {
      const body = await parseRequestBody(req);
      if (!body.amount || body.amount <= 0) {
        return sendJSON(res, 400, { error: 'INVALID_AMOUNT', message: 'Deposit amount must be positive.' });
      }
      const newDeposit = {
        id: `dep-${Date.now()}`,
        transactionId: `TXN-DEP-${Math.floor(100000 + Math.random()*900000)}`,
        userId,
        amount: parseFloat(body.amount),
        currency: body.currency || 'USD',
        status: 'PENDING',
        paymentMethod: body.paymentMethod || 'BANK_WIRE',
        proofUrl: body.proofUrl || null,
        createdAt: new Date().toISOString()
      };
      db.deposits.unshift(newDeposit);
      return sendJSON(res, 201, { message: 'Deposit request submitted for admin review.', deposit: newDeposit });
    }

    // Withdrawals Endpoint
    if (pathname === '/api/v1/client/withdrawals' && method === 'GET') {
      const withdrawals = db.withdrawals.filter(w => w.userId === userId);
      return sendJSON(res, 200, { withdrawals });
    }

    if (pathname === '/api/v1/client/withdrawals' && method === 'POST') {
      const body = await parseRequestBody(req);
      if (!body.amount || body.amount <= 0) {
        return sendJSON(res, 400, { error: 'INVALID_AMOUNT', message: 'Withdrawal amount must be positive.' });
      }
      if (!body.destinationAddress) {
        return sendJSON(res, 400, { error: 'MISSING_ADDRESS', message: 'Destination payment address required.' });
      }
      const newWithdrawal = {
        id: `wth-${Date.now()}`,
        transactionId: `TXN-WTH-${Math.floor(100000 + Math.random()*900000)}`,
        userId,
        amount: parseFloat(body.amount),
        currency: body.currency || 'USD',
        status: 'PENDING',
        destinationAddress: body.destinationAddress,
        paymentMethod: body.paymentMethod || 'BANK_WIRE',
        createdAt: new Date().toISOString()
      };
      db.withdrawals.unshift(newWithdrawal);
      return sendJSON(res, 201, { message: 'Withdrawal request submitted for compliance review.', withdrawal: newWithdrawal });
    }
  }

  // ---------------------------------------------------------
  // ADMIN PORTAL PROTECTED ENDPOINTS (FULL ACCESS & AUDIT LOGGED)
  // ---------------------------------------------------------
  if (pathname.startsWith('/api/v1/admin/')) {
    const authHeader = req.headers['authorization'];
    const token = authHeader && authHeader.startsWith('Bearer ') ? authHeader.substring(7) : null;
    const payload = verifyJWT(token, JWT_ADMIN_SECRET);
    if (!payload || !['ADMIN', 'SUPER_ADMIN', 'COMPLIANCE_OFFICER'].includes(payload.role)) {
      return sendJSON(res, 401, { error: 'UNAUTHORIZED_ADMIN_ACCESS', message: 'Valid Admin JWT token required.' });
    }

    const adminId = payload.adminId;

    // Overview Stats
    if (pathname === '/api/v1/admin/overview' && method === 'GET') {
      return sendJSON(res, 200, {
        metrics: {
          totalClients: db.users.length,
          pendingKYCs: db.kycProfiles.filter(k => k.status === 'PENDING').length,
          pendingDeposits: db.deposits.filter(d => d.status === 'PENDING').length,
          pendingWithdrawals: db.withdrawals.filter(w => w.status === 'PENDING').length,
          activeAccounts: db.tradingAccounts.length,
          totalAUM: db.tradingAccounts.reduce((s, a) => s + (parseFloat(a.balance) || 0), 0)
        },
        botStatus: db.botStatus
      });
    }

    // Manage Clients List
    if (pathname === '/api/v1/admin/clients' && method === 'GET') {
      const clients = db.users.map(u => {
        const kyc = db.kycProfiles.find(k => k.userId === u.id);
        const mappedAccIds = db.accountUserMappings.filter(m => m.userId === u.id).map(m => m.tradingAccountId);
        return {
          ...u,
          kycStatus: kyc ? kyc.status : 'NOT_SUBMITTED',
          mappedAccountIds: mappedAccIds
        };
      });
      return sendJSON(res, 200, { clients });
    }

    // Approve / Reject KYC
    if (pathname === '/api/v1/admin/kyc/action' && method === 'POST') {
      const body = await parseRequestBody(req);
      const kyc = db.kycProfiles.find(k => k.id === body.kycId || k.userId === body.userId);
      if (!kyc) return sendJSON(res, 404, { error: 'KYC_NOT_FOUND' });

      kyc.status = body.status; // 'APPROVED' or 'REJECTED'
      kyc.rejectionReason = body.rejectionReason || null;
      kyc.reviewedByAdminId = adminId;
      kyc.reviewedAt = new Date().toISOString();

      logAudit(adminId, null, `KYC_${body.status}`, `KYC:${kyc.id}`, req.socket.remoteAddress, { userId: kyc.userId, status: body.status });
      return sendJSON(res, 200, { message: `KYC profile updated to ${body.status}`, kyc });
    }

    // Approve / Reject Deposits
    if (pathname === '/api/v1/admin/deposits/action' && method === 'POST') {
      const body = await parseRequestBody(req);
      const dep = db.deposits.find(d => d.id === body.depositId);
      if (!dep) return sendJSON(res, 404, { error: 'DEPOSIT_NOT_FOUND' });

      dep.status = body.status; // 'COMPLETED' or 'REJECTED'
      dep.reviewedByAdminId = adminId;
      dep.updatedAt = new Date().toISOString();

      logAudit(adminId, null, `DEPOSIT_${body.status}`, `Deposit:${dep.id}`, req.socket.remoteAddress, { amount: dep.amount, userId: dep.userId });
      return sendJSON(res, 200, { message: `Deposit marked as ${body.status}`, deposit: dep });
    }

    // Approve / Reject Withdrawals
    if (pathname === '/api/v1/admin/withdrawals/action' && method === 'POST') {
      const body = await parseRequestBody(req);
      const wth = db.withdrawals.find(w => w.id === body.withdrawalId);
      if (!wth) return sendJSON(res, 404, { error: 'WITHDRAWAL_NOT_FOUND' });

      wth.status = body.status; // 'COMPLETED' or 'REJECTED'
      wth.reviewedByAdminId = adminId;
      wth.processedRefId = body.processedRefId || `REF-${Date.now()}`;
      wth.updatedAt = new Date().toISOString();

      logAudit(adminId, null, `WITHDRAWAL_${body.status}`, `Withdrawal:${wth.id}`, req.socket.remoteAddress, { amount: wth.amount, userId: wth.userId });
      return sendJSON(res, 200, { message: `Withdrawal marked as ${body.status}`, withdrawal: wth });
    }

    // Audit Logs
    if (pathname === '/api/v1/admin/audit-logs' && method === 'GET') {
      return sendJSON(res, 200, { auditLogs: db.auditLogs });
    }
  }

  // Fallback 404
  return sendJSON(res, 404, { error: 'NOT_FOUND', message: `Route ${pathname} not found.` });
});

server.listen(PORT, () => {
  console.log(`=======================================================`);
  console.log(` PKG TRADERS CENTRAL BACKEND API SERVER RUNNING`);
  console.log(` Port:            ${PORT}`);
  console.log(` Telemetry Route: POST /api/v1/bot/sync (HMAC Guard)`);
  console.log(` Client Route:    /api/v1/client/*`);
  console.log(` Admin Route:     /api/v1/admin/*`);
  console.log(`=======================================================`);
});
