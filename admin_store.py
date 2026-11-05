"""Server-side settings and password-only access. Never send this store to clients."""

from contextlib import contextmanager
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path

ITERATIONS = 600_000
SESSION_SECONDS = 12 * 60 * 60
MAX_FAILURES = 10
LOCK_SECONDS = 60


class AccessDenied(ValueError):
    pass


class LoginLimited(ValueError):
    pass


def validate_password(password):
    if not isinstance(password, str) or not 8 <= len(password) <= 256 or not password.strip():
        raise ValueError("รหัสผ่านต้องมี 8–256 ตัวอักษร")


def hash_password(password):
    validate_password(password)
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest}"


def verify_password(password, encoded):
    if not isinstance(password, str) or len(password) > 256 or not encoded:
        return False
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or int(iterations) != ITERATIONS:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def credential(password):
    return {"hash": hash_password(password), "version": secrets.token_hex(32)}


class SettingsStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS login_limit (id INTEGER PRIMARY KEY CHECK(id=1), failures INTEGER NOT NULL, started REAL NOT NULL, blocked_until REAL NOT NULL)")
            db.execute("INSERT OR IGNORE INTO settings VALUES (1, ?)", (json.dumps({
                "admin": None, "member": None, "api_key": "", "model": ""
            }),))
            db.execute("INSERT OR IGNORE INTO login_limit VALUES (1, 0, 0, 0)")

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _read(db):
        return json.loads(db.execute("SELECT value FROM settings WHERE id=1").fetchone()[0])

    @staticmethod
    def _write(db, config):
        db.execute("UPDATE settings SET value=? WHERE id=1", (json.dumps(config),))

    def configured(self):
        with self._connection() as db:
            return bool(self._read(db)["admin"])

    def bootstrap(self, admin_password, member_password="", api_key="", model=""):
        """One-time initialization from a trusted CLI or server secrets, never a public form."""
        with self._connection() as db:
            config = self._read(db)
            if config["admin"] or not admin_password:
                return False
            if member_password and hmac.compare_digest(admin_password.encode(), member_password.encode()):
                raise ValueError("รหัสผู้ดูแลและรหัสสมาชิกต้องต่างกัน")
            config.update(admin=credential(admin_password),
                          member=credential(member_password) if member_password else None,
                          api_key=api_key.strip(), model=model.strip())
            self._write(db, config)
            return True

    @staticmethod
    def _role(config, ticket):
        if not isinstance(ticket, dict):
            return None
        role = ticket.get("role")
        stored = config.get(role) if role in ("admin", "member") else None
        if (not stored or not isinstance(ticket.get("version"), str)
                or not isinstance(ticket.get("expires"), (int, float))
                or not ticket["expires"] > time.time()):
            return None
        return role if hmac.compare_digest(stored["version"], ticket["version"]) else None

    def role(self, ticket):
        with self._connection() as db:
            return self._role(self._read(db), ticket)

    @classmethod
    def _require(cls, config, ticket, admin=False):
        role = cls._role(config, ticket)
        if not role or (admin and role != "admin"):
            raise AccessDenied("กรุณาเข้าสู่ระบบอีกครั้งด้วยสิทธิ์ที่ถูกต้อง")

    def login(self, password):
        # A shared server-side bucket survives reconnects; no trust in client-provided IPs.
        # Commit failed attempts before raising/returning so refreshing cannot reset them.
        with self._connection() as db:
            config = self._read(db)
            failures, started, blocked = db.execute(
                "SELECT failures, started, blocked_until FROM login_limit WHERE id=1").fetchone()
            now = time.time()
            if blocked > now:
                raise LoginLimited("กรอกรหัสผิดหลายครั้ง กรุณารอ 1 นาทีแล้วลองใหม่")
            if now - started >= 300 or (blocked and blocked <= now):
                failures, started = 0, now
            matched = None
            for role in ("member", "admin"):
                if config[role] and verify_password(password, config[role]["hash"]):
                    matched = role
            if matched:
                db.execute("UPDATE login_limit SET failures=0, started=0, blocked_until=0 WHERE id=1")
                return {"role": matched, "version": config[matched]["version"],
                        "expires": now + SESSION_SECONDS}
            failures += 1
            db.execute("UPDATE login_limit SET failures=?, started=?, blocked_until=? WHERE id=1",
                       (failures, started, now + LOCK_SECONDS if failures >= MAX_FAILURES else 0))
            return None

    def summary(self, ticket):
        with self._connection() as db:
            config = self._read(db)
            self._require(config, ticket, admin=True)
            return {"has_api_key": bool(config["api_key"]), "model": config["model"],
                    "has_member_password": bool(config["member"])}

    def ai_credentials(self, ticket):
        with self._connection() as db:
            config = self._read(db)
            self._require(config, ticket)
            return config["api_key"], config["model"]

    def save_ai(self, ticket, api_key, model, clear_key=False):
        model, api_key = model.strip(), api_key.strip()
        if len(model) > 200 or len(api_key) > 500 or any(c in model + api_key for c in "\r\n"):
            raise ValueError("API key หรือชื่อโมเดลมีรูปแบบไม่ถูกต้อง")
        if clear_key and api_key:
            raise ValueError("เลือกอย่างใดอย่างหนึ่ง: ใส่คีย์ใหม่ หรือลบคีย์เดิม")
        with self._connection() as db:
            config = self._read(db)
            self._require(config, ticket, admin=True)
            if (api_key or (config["api_key"] and not clear_key)) and not model:
                raise ValueError("กรุณาระบุชื่อโมเดล")
            if clear_key:
                config["api_key"] = ""
            elif api_key:
                config["api_key"] = api_key
            config["model"] = model
            self._write(db, config)

    def change_password(self, ticket, role, password):
        if role not in ("admin", "member"):
            raise ValueError("ประเภทผู้ใช้ไม่ถูกต้อง")
        validate_password(password)
        with self._connection() as db:
            config = self._read(db)
            self._require(config, ticket, admin=True)
            other = config["member" if role == "admin" else "admin"]
            if other and verify_password(password, other["hash"]):
                raise ValueError("รหัสผู้ดูแลและรหัสสมาชิกต้องต่างกัน")
            config[role] = credential(password)
            self._write(db, config)

    def reset_admin_locally(self, password):
        """Recovery is available only to the server operator through the CLI."""
        validate_password(password)
        with self._connection() as db:
            config = self._read(db)
            if config["member"] and verify_password(password, config["member"]["hash"]):
                raise ValueError("รหัสผู้ดูแลและรหัสสมาชิกต้องต่างกัน")
            config["admin"] = credential(password)
            self._write(db, config)
            db.execute("UPDATE login_limit SET failures=0, started=0, blocked_until=0 WHERE id=1")
