"""Accounts and sessions. Who may send mail from this account.

Sending is the only thing that needs an identity: it leaves the building
under the shipping desk's own address. Reading is left open so anyone given
the link can see the queue without being handed credentials first - set
SDOC_REQUIRE_LOGIN=1 to close that too.

Registration needs a code. This app runs on a public URL, and open signup
plus the ability to send is an open relay wearing a hat: a stranger signs
up, then mails the world from this account. The code is typed once, when
the account is created, and never again - which is the whole point of
having sessions rather than a passphrase on every send.

Passwords are stored as scrypt hashes with a per-password salt. stdlib
only: no dependency worth adding for one call.
"""
import base64
import hashlib
import json
import logging
import os
import secrets
from pathlib import Path

from sdoc.config import OUT_DIR

log = logging.getLogger(__name__)

USERS_FILE = "users.json"
SESSION_KEY = "user"

# scrypt cost. 2**14 keeps a login around 50ms here - slow enough to make
# guessing expensive, fast enough that a demo does not feel broken.
_N, _R, _P, _DKLEN = 2 ** 14, 8, 1, 32
_MAXMEM = 64 * 1024 * 1024

MIN_PASSWORD = 8


def _dir(out_dir: Path | None) -> Path:
    return Path(out_dir) if out_dir is not None else Path(OUT_DIR)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P,
                         dklen=_DKLEN, maxmem=_MAXMEM)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(key).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_b64, key_b64 = (stored or "").split("$")
        if algo != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(key_b64)
    except Exception:
        return False
    key = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P,
                         dklen=_DKLEN, maxmem=_MAXMEM)
    return secrets.compare_digest(key, expected)


def load_users(out_dir: Path | None = None) -> dict:
    path = _dir(out_dir) / USERS_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("%s is not readable JSON; treating it as empty", path)
        return {}


def save_users(users: dict, out_dir: Path | None = None) -> None:
    base = _dir(out_dir)
    base.mkdir(parents=True, exist_ok=True)
    (base / USERS_FILE).write_text(json.dumps(users, indent=2), encoding="utf-8")


def signup_code() -> str | None:
    return os.environ.get("SDOC_SIGNUP_CODE") or None


def signup_open() -> bool:
    """No code configured means no new accounts. Closed is the safe default:
    a public URL where anyone can sign up and then send is an open relay."""
    return bool(signup_code())


def code_ok(supplied: str) -> bool:
    expected = signup_code()
    if not expected:
        return False
    return secrets.compare_digest(supplied or "", expected)


def require_login() -> bool:
    """Whether reading needs an account too. Off by default."""
    return os.environ.get("SDOC_REQUIRE_LOGIN", "0") == "1"


def normalise(email: str) -> str:
    return (email or "").strip().lower()


def create_user(email: str, password: str, out_dir: Path | None = None) -> dict:
    """Caller checks the signup code. Raises ValueError with a message meant
    to be shown to the person."""
    email = normalise(email)
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ValueError("that does not look like an email address")
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
    users = load_users(out_dir)
    if email in users:
        raise ValueError("an account with that email already exists")
    users[email] = {"email": email, "password": hash_password(password)}
    save_users(users, out_dir)
    return users[email]


def authenticate(email: str, password: str, out_dir: Path | None = None) -> str | None:
    """The account's email, or None. Never says which half was wrong."""
    email = normalise(email)
    user = load_users(out_dir).get(email)
    if not user or not verify_password(password or "", user.get("password", "")):
        return None
    return email


def current_user(request) -> str | None:
    try:
        return request.session.get(SESSION_KEY)
    except (AssertionError, AttributeError):
        return None       # SessionMiddleware not installed (unit tests)


def session_secret() -> str:
    """A generated secret means sessions do not survive a restart - people
    get logged out on every deploy. Fine locally, worth setting in prod."""
    secret = os.environ.get("SDOC_SECRET_KEY")
    if not secret:
        log.info("SDOC_SECRET_KEY not set - sessions will not survive a restart")
        secret = secrets.token_urlsafe(32)
    return secret
