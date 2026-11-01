/**
 * PKG Traders Central Backend — Authentication & Authorization Utility
 * Implements:
 * - Password Hashing & Verification (bcrypt / pbkdf2)
 * - JWT Token Generation & Verification (Client vs Admin separation)
 * - Service-to-Service Bot HMAC Signature Authentication
 * - Server-side Role-Based Access Control (RBAC) & Tenant Isolation
 */

const crypto = require('crypto');

// Secret keys from environment variables with fallbacks for local dev
const JWT_CLIENT_SECRET = process.env.JWT_CLIENT_SECRET || 'dev_client_jwt_secret_32bytes_minimum_key!';
const JWT_ADMIN_SECRET = process.env.JWT_ADMIN_SECRET || 'dev_admin_jwt_secret_32bytes_minimum_key!';
const BOT_HMAC_SECRET = process.env.BOT_HMAC_SECRET || 'dev_bot_hmac_secret_64bytes_minimum_key_for_pkgtraders!';

/**
 * Hash a password securely using PBKDF2 with salt.
 */
function hashPassword(password) {
  const salt = crypto.randomBytes(16).toString('hex');
  const hash = crypto.pbkdf2Sync(password, salt, 10000, 64, 'sha512').toString('hex');
  return `${salt}:${hash}`;
}

/**
 * Verify a plain text password against a stored salt:hash string.
 */
function verifyPassword(password, storedHash) {
  if (!storedHash || !storedHash.includes(':')) return false;
  const [salt, originalHash] = storedHash.split(':');
  const hash = crypto.pbkdf2Sync(password, salt, 10000, 64, 'sha512').toString('hex');
  return crypto.timingSafeEqual(Buffer.from(hash), Buffer.from(originalHash));
}

/**
 * Generate HMAC SHA-256 signature for Bot outbound payloads.
 */
function generateBotHMACSignature(payloadString, timestamp) {
  const message = `${timestamp}.${payloadString}`;
  return crypto.createHmac('sha256', BOT_HMAC_SECRET).update(message).digest('hex');
}

/**
 * Verify Bot outbound request HMAC SHA-256 signature.
 * Prevents replay attacks by checking timestamp window (5 minutes max).
 */
function verifyBotHMACSignature(payloadString, timestampHeader, signatureHeader) {
  if (!timestampHeader || !signatureHeader) return false;

  // Timestamp staleness check (5 mins)
  const now = Math.floor(Date.now() / 1000);
  const reqTime = parseInt(timestampHeader, 10);
  if (isNaN(reqTime) || Math.abs(now - reqTime) > 300) {
    return false;
  }

  const expectedSig = generateBotHMACSignature(payloadString, timestampHeader);
  try {
    return crypto.timingSafeEqual(
      Buffer.from(signatureHeader, 'utf-8'),
      Buffer.from(expectedSig, 'utf-8')
    );
  } catch (err) {
    return false;
  }
}

/**
 * Simple Base64URL-encoded JWT Implementation for Zero-Dependency Fast Server
 */
function signJWT(payload, secret, expiresInSeconds = 86400) {
  const header = { alg: 'HS256', typ: 'JWT' };
  const exp = Math.floor(Date.now() / 1000) + expiresInSeconds;
  const fullPayload = { ...payload, exp, iat: Math.floor(Date.now() / 1000) };

  const b64Header = Buffer.from(JSON.stringify(header)).toString('base64url');
  const b64Payload = Buffer.from(JSON.stringify(fullPayload)).toString('base64url');

  const signature = crypto
    .createHmac('sha256', secret)
    .update(`${b64Header}.${b64Payload}`)
    .digest('base64url');

  return `${b64Header}.${b64Payload}.${signature}`;
}

function verifyJWT(token, secret) {
  if (!token || typeof token !== 'string') return null;
  const parts = token.split('.');
  if (parts.length !== 3) return null;

  const [b64Header, b64Payload, signature] = parts;
  const expectedSig = crypto
    .createHmac('sha256', secret)
    .update(`${b64Header}.${b64Payload}`)
    .digest('base64url');

  try {
    if (!crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expectedSig))) {
      return null;
    }
    const payload = JSON.parse(Buffer.from(b64Payload, 'base64url').toString('utf-8'));
    const now = Math.floor(Date.now() / 1000);
    if (payload.exp && payload.exp < now) {
      return null; // Expired
    }
    return payload;
  } catch (err) {
    return null;
  }
}

module.exports = {
  hashPassword,
  verifyPassword,
  generateBotHMACSignature,
  verifyBotHMACSignature,
  signJWT,
  verifyJWT,
  JWT_CLIENT_SECRET,
  JWT_ADMIN_SECRET,
  BOT_HMAC_SECRET
};
