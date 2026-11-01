"""
web/backend/server.py — Central Backend API Service (Python Edition)

Architecture:
- Native Python 3.11 standalone backend service.
- Strict tenant isolation for Client Portal.
- Role-Based Access Control (RBAC) & Audit Logging for Admin Portal.
- Outbound HMAC-SHA256 authenticated telemetry ingestion for Trading Bot PC.
- Exposes REST endpoints on http://localhost:4000.
"""

from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
import sys
import time
import base64
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] [BACKEND_SERVER] %(message)s')
logger = logging.getLogger("backend_server")

PORT = int(os.getenv("PORT", "4000"))
JWT_CLIENT_SECRET = os.getenv("JWT_CLIENT_SECRET", "dev_client_jwt_secret_32bytes_minimum_key!")
JWT_ADMIN_SECRET = os.getenv("JWT_ADMIN_SECRET", "dev_admin_jwt_secret_32bytes_minimum_key!")
BOT_HMAC_SECRET = os.getenv("BOT_HMAC_SECRET", "dev_bot_hmac_secret_64bytes_minimum_key_for_pkgtraders!")


# ---------------------------------------------------------
# SECURITY & AUTHENTICATION UTILITIES
# ---------------------------------------------------------
def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    key = hashlib.pbkdf2_hmac('sha512', password.encode('utf-8'), salt.encode('utf-8'), 10000)
    return f"{salt}:{key.hex()}"

def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash or ':' not in stored_hash:
        return False
    salt, original = stored_hash.split(':')
    key = hashlib.pbkdf2_hmac('sha512', password.encode('utf-8'), salt.encode('utf-8'), 10000)
    return hmac.compare_digest(key.hex(), original)

def generate_bot_hmac(payload_json: str, timestamp_str: str) -> str:
    msg = f"{timestamp_str}.{payload_json}".encode('utf-8')
    return hmac.new(BOT_HMAC_SECRET.encode('utf-8'), msg, hashlib.sha256).hexdigest()

def verify_bot_hmac(payload_json: str, timestamp_str: Optional[str], signature_str: Optional[str]) -> bool:
    if not timestamp_str or not signature_str:
        return False
    try:
        req_time = int(timestamp_str)
        now = int(time.time())
        if abs(now - req_time) > 300: # 5 min timestamp freshness limit
            return False
        expected = generate_bot_hmac(payload_json, timestamp_str)
        return hmac.compare_digest(expected, signature_str)
    except Exception:
        return False

def sign_jwt(payload: Dict[str, Any], secret: str, expires_in_sec: int = 86400) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    exp = int(time.time()) + expires_in_sec
    full_payload = {**payload, "exp": exp, "iat": int(time.time())}
    
    b64_header = base64.urlsafe_b64encode(json.dumps(header).encode('utf-8')).decode('utf-8').rstrip('=')
    b64_payload = base64.urlsafe_b64encode(json.dumps(full_payload).encode('utf-8')).decode('utf-8').rstrip('=')
    
    msg = f"{b64_header}.{b64_payload}".encode('utf-8')
    sig = hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).digest()
    b64_sig = base64.urlsafe_b64encode(sig).decode('utf-8').rstrip('=')
    return f"{b64_header}.{b64_payload}.{b64_sig}"

def verify_jwt(token: str, secret: str) -> Optional[Dict[str, Any]]:
    if not token or not isinstance(token, str):
        return None
    parts = token.split('.')
    if len(parts) != 3:
        return None
    b64_h, b64_p, sig = parts
    msg = f"{b64_h}.{b64_p}".encode('utf-8')
    expected_sig = base64.urlsafe_b64encode(hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).digest()).decode('utf-8').rstrip('=')
    if not hmac.compare_digest(expected_sig, sig):
        return None
    try:
        padded_p = b64_p + '=' * (-len(b64_p) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded_p).decode('utf-8'))
        if payload.get("exp", 0) < int(time.time()):
            return None # Expired
        return payload
    except Exception:
        return None


# ---------------------------------------------------------
# IN-MEMORY DATABASE STORE (PRISMA SCHEMA PARITY)
# ---------------------------------------------------------
DB: Dict[str, List[Dict[str, Any]]] = {
    "users": [
        {
            "id": "usr-client-001",
            "email": "client@pkgtraders.com",
            "passwordHash": hash_password("ClientPass123!"),
            "firstName": "Gagan",
            "lastName": "Trader",
            "isSuspended": False,
            "createdAt": datetime.now(timezone.utc).isoformat()
        }
    ],
    "adminUsers": [
        {
            "id": "usr-admin-001",
            "email": "admin@pkgtraders.com",
            "passwordHash": hash_password("AdminPass123!"),
            "firstName": "System",
            "lastName": "Administrator",
            "roleType": "SUPER_ADMIN",
            "isActive": True,
            "createdAt": datetime.now(timezone.utc).isoformat()
        }
    ],
    "kycProfiles": [
        {
            "id": "kyc-001",
            "userId": "usr-client-001",
            "status": "APPROVED",
            "rejectionReason": None,
            "reviewedByAdminId": "usr-admin-001",
            "submittedAt": datetime.now(timezone.utc).isoformat(),
            "documents": [
                {"id": "doc-001", "type": "PASSPORT", "fileUrl": "https://storage.pkgtraders.com/kyc/passport_001.pdf", "uploadedAt": datetime.now(timezone.utc).isoformat()}
            ]
        }
    ],
    "tradingAccounts": [
        {
            "id": "ta-001",
            "mt5Login": 26128885,
            "accountName": "Standard Vantage Account 1",
            "magicNumber": 20250701,
            "currency": "USD",
            "balance": 495.37,
            "equity": 483.96,
            "margin": 18.56,
            "freeMargin": 465.40,
            "marginLevel": 2607.54,
            "status": "ACTIVE",
            "lastSyncAt": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": "ta-003",
            "mt5Login": 26179878,
            "accountName": "Standard Vantage Account 3",
            "magicNumber": 20250703,
            "currency": "USD",
            "balance": 1000.00,
            "equity": 1000.00,
            "margin": 0.00,
            "freeMargin": 1000.00,
            "marginLevel": 0.00,
            "status": "ACTIVE",
            "lastSyncAt": datetime.now(timezone.utc).isoformat()
        }
    ],
    "accountUserMappings": [
        {"id": "map-001", "userId": "usr-client-001", "tradingAccountId": "ta-001"},
        {"id": "map-002", "userId": "usr-client-001", "tradingAccountId": "ta-003"}
    ],
    "openPositions": [],
    "trades": [],
    "deposits": [
        {
            "id": "dep-001",
            "transactionId": "TXN-DEP-1001",
            "userId": "usr-client-001",
            "amount": 500.00,
            "currency": "USD",
            "status": "COMPLETED",
            "paymentMethod": "BANK_WIRE",
            "proofUrl": "https://storage.pkgtraders.com/proofs/dep_1001.pdf",
            "createdAt": datetime.now(timezone.utc).isoformat()
        }
    ],
    "withdrawals": [
        {
            "id": "wth-001",
            "transactionId": "TXN-WTH-2001",
            "userId": "usr-client-001",
            "amount": 50.00,
            "currency": "USD",
            "status": "PENDING",
            "destinationAddress": "US8937000123456789",
            "paymentMethod": "BANK_WIRE",
            "createdAt": datetime.now(timezone.utc).isoformat()
        }
    ],
    "auditLogs": [
        {
            "id": "aud-001",
            "actorAdminId": "usr-admin-001",
            "action": "SYSTEM_INITIALIZED",
            "targetEntity": "System:Backend",
            "ipAddress": "127.0.0.1",
            "metadata": json.dumps({"version": "2.0.0"}),
            "createdAt": datetime.now(timezone.utc).isoformat()
        }
    ]
}

BOT_STATUS = {
    "instanceName": "TRADING_BOT_PC_01",
    "pcHostname": "TRADING-DESKTOP",
    "botVersion": "2.0.0",
    "status": "ONLINE",
    "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
    "activeAccountCount": 2
}


def log_audit(admin_id: Optional[str], user_id: Optional[str], action: str, target: str, ip: str, metadata: Any):
    entry = {
        "id": f"aud-{int(time.time()*1000)}",
        "actorAdminId": admin_id,
        "actorUserId": user_id,
        "action": action,
        "targetEntity": target,
        "ipAddress": ip,
        "metadata": json.dumps(metadata) if isinstance(metadata, dict) else str(metadata),
        "createdAt": datetime.now(timezone.utc).isoformat()
    }
    DB["auditLogs"].insert(0, entry)


class CentralBackendHandler(BaseHTTPRequestHandler):

    def _send_json(self, status_code: int, data: Dict[str, Any]):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Bot-Api-Key, X-Bot-Timestamp, X-Bot-Signature')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Bot-Api-Key, X-Bot-Timestamp, X-Bot-Signature')
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get('Content-Length', 0))
        raw_body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""

        # ---------------------------------------------------------
        # 1. BOT TELEMETRY INGESTION (HMAC GUARD)
        # ---------------------------------------------------------
        if path == "/api/v1/bot/sync":
            ts = self.headers.get("X-Bot-Timestamp")
            sig = self.headers.get("X-Bot-Signature")
            if not verify_bot_hmac(raw_body, ts, sig):
                return self._send_json(401, {"error": "UNAUTHORIZED_BOT_SIGNATURE", "message": "HMAC signature invalid or timestamp stale."})

            try:
                payload = json.loads(raw_body)
                BOT_STATUS.update({
                    "instanceName": payload.get("instance_name", "TRADING_BOT_PC_01"),
                    "pcHostname": payload.get("pc_hostname", "WINDOWS-PC"),
                    "botVersion": payload.get("bot_version", "2.0.0"),
                    "status": "ONLINE",
                    "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
                    "activeAccountCount": len(payload.get("accounts", []))
                })

                for acc in payload.get("accounts", []):
                    existing = next((a for a in DB["tradingAccounts"] if a["mt5Login"] == acc["mt5_login"]), None)
                    if existing:
                        existing.update({
                            "balance": acc["balance"],
                            "equity": acc["equity"],
                            "margin": acc["margin"],
                            "freeMargin": acc["free_margin"],
                            "marginLevel": acc["margin_level"],
                            "lastSyncAt": datetime.now(timezone.utc).isoformat()
                        })
                    else:
                        acc_obj = {
                            "id": f"ta-{acc['mt5_login']}",
                            "mt5Login": acc["mt5_login"],
                            "accountName": f"Account #{acc['mt5_login']}",
                            "magicNumber": acc["magic_number"],
                            "currency": "USD",
                            "balance": acc["balance"],
                            "equity": acc["equity"],
                            "margin": acc["margin"],
                            "freeMargin": acc["free_margin"],
                            "marginLevel": acc["margin_level"],
                            "status": "ACTIVE",
                            "lastSyncAt": datetime.now(timezone.utc).isoformat()
                        }
                        DB["tradingAccounts"].append(acc_obj)

                return self._send_json(200, {"status": "SUCCESS", "message": "Telemetry snapshot synchronized cleanly."})
            except Exception as e:
                return self._send_json(400, {"error": "INVALID_PAYLOAD", "message": str(e)})

        # Parse JSON body for rest of endpoints
        body = json.loads(raw_body) if raw_body else {}

        # Client Auth Login
        if path == "/api/v1/client/auth/login":
            user = next((u for u in DB["users"] if u["email"] == body.get("email")), None)
            if not user or not verify_password(body.get("password", ""), user["passwordHash"]):
                return self._send_json(401, {"error": "INVALID_CREDENTIALS", "message": "Invalid email or password."})
            if user["isSuspended"]:
                return self._send_json(403, {"error": "ACCOUNT_SUSPENDED", "message": "Account suspended."})
            token = sign_jwt({"userId": user["id"], "email": user["email"], "role": "CLIENT"}, JWT_CLIENT_SECRET)
            return self._send_json(200, {"token": token, "user": {"id": user["id"], "email": user["email"], "firstName": user["firstName"], "lastName": user["lastName"]}})

        # Admin Auth Login
        if path == "/api/v1/admin/auth/login":
            admin = next((a for a in DB["adminUsers"] if a["email"] == body.get("email")), None)
            if not admin or not verify_password(body.get("password", ""), admin["passwordHash"]):
                return self._send_json(401, {"error": "INVALID_CREDENTIALS", "message": "Invalid admin credentials."})
            log_audit(admin["id"], None, "ADMIN_LOGIN", f"Admin:{admin['email']}", self.client_address[0], {"timestamp": datetime.now(timezone.utc).isoformat()})
            token = sign_jwt({"adminId": admin["id"], "email": admin["email"], "role": admin["roleType"]}, JWT_ADMIN_SECRET)
            return self._send_json(200, {"token": token, "admin": {"id": admin["id"], "email": admin["email"], "firstName": admin["firstName"], "lastName": admin["lastName"], "role": admin["roleType"]}})

        # Client Deposits Request
        if path == "/api/v1/client/deposits":
            user = self._auth_client()
            if not user: return
            amount = float(body.get("amount", 0.0))
            if amount <= 0:
                return self._send_json(400, {"error": "INVALID_AMOUNT", "message": "Deposit amount must be > 0"})
            dep = {
                "id": f"dep-{int(time.time()*1000)}",
                "transactionId": f"TXN-DEP-{int(time.time())}",
                "userId": user["userId"],
                "amount": amount,
                "currency": body.get("currency", "USD"),
                "status": "PENDING",
                "paymentMethod": body.get("paymentMethod", "BANK_WIRE"),
                "proofUrl": body.get("proofUrl"),
                "createdAt": datetime.now(timezone.utc).isoformat()
            }
            DB["deposits"].insert(0, dep)
            return self._send_json(201, {"message": "Deposit request submitted.", "deposit": dep})

        # Client Withdrawals Request
        if path == "/api/v1/client/withdrawals":
            user = self._auth_client()
            if not user: return
            amount = float(body.get("amount", 0.0))
            if amount <= 0 or not body.get("destinationAddress"):
                return self._send_json(400, {"error": "INVALID_INPUT", "message": "Amount and destination address required."})
            wth = {
                "id": f"wth-{int(time.time()*1000)}",
                "transactionId": f"TXN-WTH-{int(time.time())}",
                "userId": user["userId"],
                "amount": amount,
                "currency": body.get("currency", "USD"),
                "status": "PENDING",
                "destinationAddress": body["destinationAddress"],
                "paymentMethod": body.get("paymentMethod", "BANK_WIRE"),
                "createdAt": datetime.now(timezone.utc).isoformat()
            }
            DB["withdrawals"].insert(0, wth)
            return self._send_json(201, {"message": "Withdrawal request submitted.", "withdrawal": wth})

        # Admin Actions (KYC Approval, Deposit, Withdrawal)
        if path == "/api/v1/admin/kyc/action":
            admin = self._auth_admin()
            if not admin: return
            kyc = next((k for k in DB["kycProfiles"] if k["id"] == body.get("kycId") or k["userId"] == body.get("userId")), None)
            if not kyc: return self._send_json(404, {"error": "NOT_FOUND"})
            kyc["status"] = body["status"]
            kyc["rejectionReason"] = body.get("rejectionReason")
            kyc["reviewedByAdminId"] = admin["adminId"]
            log_audit(admin["adminId"], None, f"KYC_{body['status']}", f"KYC:{kyc['id']}", self.client_address[0], {"userId": kyc["userId"]})
            return self._send_json(200, {"message": f"KYC updated to {body['status']}", "kyc": kyc})

        return self._send_json(404, {"error": "ROUTE_NOT_FOUND"})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/v1/health":
            return self._send_json(200, {"status": "HEALTHY", "botStatus": BOT_STATUS, "timestamp": datetime.now(timezone.utc).isoformat()})

        # Client Dashboard (Tenant Isolated)
        if path == "/api/v1/client/dashboard":
            user = self._auth_client()
            if not user: return
            user_id = user["userId"]
            user_obj = next((u for u in DB["users"] if u["id"] == user_id), None)
            mapped_ids = [m["tradingAccountId"] for m in DB["accountUserMappings"] if m["userId"] == user_id]
            accounts = [a for a in DB["tradingAccounts"] if a["id"] in mapped_ids]
            kyc = next((k for k in DB["kycProfiles"] if k["userId"] == user_id), None)
            total_bal = sum(a["balance"] for a in accounts)
            total_eq = sum(a["equity"] for a in accounts)

            return self._send_json(200, {
                "user": {"id": user_obj["id"], "email": user_obj["email"], "firstName": user_obj["firstName"], "lastName": user_obj["lastName"]},
                "kycStatus": kyc["status"] if kyc else "NOT_SUBMITTED",
                "financials": {
                    "totalBalance": total_bal,
                    "totalEquity": total_eq,
                    "accountCount": len(accounts)
                },
                "accounts": accounts,
                "deposits": [d for d in DB["deposits"] if d["userId"] == user_id],
                "withdrawals": [w for w in DB["withdrawals"] if w["userId"] == user_id]
            })

        # Admin Overview & Management
        if path == "/api/v1/admin/overview":
            admin = self._auth_admin()
            if not admin: return
            return self._send_json(200, {
                "metrics": {
                    "totalClients": len(DB["users"]),
                    "pendingKYCs": len([k for k in DB["kycProfiles"] if k["status"] == "PENDING"]),
                    "pendingDeposits": len([d for d in DB["deposits"] if d["status"] == "PENDING"]),
                    "pendingWithdrawals": len([w for w in DB["withdrawals"] if w["status"] == "PENDING"]),
                    "totalAUM": sum(a["balance"] for a in DB["tradingAccounts"])
                },
                "botStatus": BOT_STATUS
            })

        if path == "/api/v1/admin/audit-logs":
            admin = self._auth_admin()
            if not admin: return
            return self._send_json(200, {"auditLogs": DB["auditLogs"]})

        return self._send_json(404, {"error": "ROUTE_NOT_FOUND"})

    def _auth_client(self) -> Optional[Dict[str, Any]]:
        auth = self.headers.get('Authorization', '')
        token = auth[7:] if auth.startswith('Bearer ') else None
        payload = verify_jwt(token, JWT_CLIENT_SECRET)
        if not payload or payload.get("role") != "CLIENT":
            self._send_json(401, {"error": "UNAUTHORIZED_CLIENT", "message": "Valid Client JWT required."})
            return None
        return payload

    def _auth_admin(self) -> Optional[Dict[str, Any]]:
        auth = self.headers.get('Authorization', '')
        token = auth[7:] if auth.startswith('Bearer ') else None
        payload = verify_jwt(token, JWT_ADMIN_SECRET)
        if not payload or payload.get("role") not in ["ADMIN", "SUPER_ADMIN", "COMPLIANCE_OFFICER"]:
            self._send_json(401, {"error": "UNAUTHORIZED_ADMIN", "message": "Valid Admin JWT required."})
            return None
        return payload


def run_server():
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, CentralBackendHandler)
    logger.info(f"PKG Traders Central Backend REST API running on http://localhost:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server shutting down.")
        httpd.server_close()

if __name__ == '__main__':
    run_server()
