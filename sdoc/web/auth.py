"""Accounts and sessions. Who gets into the terminal.

An account is needed to reach the queue at all, the way a mail service
works: the sign-in screen is the front door. SDOC_REQUIRE_LOGIN=0 opens
reading again for anyone who would rather hand out a link than credentials.

Signup is open: anyone can create their own operator account, the way any
mail service works. Setting SDOC_SIGNUP_CODE adds a code to the form if a
deployment wants to close it.

Passwords are stored as scrypt hashes with a per-password salt. stdlib
only: no dependency worth adding for one call.
"""
import base64
import hashlib
import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from sdoc.config import OUT_DIR
from sdoc.web import i18n

log = logging.getLogger(__name__)

USERS_FILE = "users.json"
SESSION_KEY = "user"

# scrypt cost. 2**14 keeps a login around 50ms here - slow enough to make
# guessing expensive, fast enough that a demo does not feel broken.
_N, _R, _P, _DKLEN = 2 ** 14, 8, 1, 32
_MAXMEM = 64 * 1024 * 1024

# The registration screen states this rule, so it is the rule.
MIN_PASSWORD = 12

# Where an operator's queue is routed. Shown on the registration form.
DESKS = [
    "ROTTERDAM-EU04",
    "SINGAPORE-APAC01",
    "DUBAI-MEA02",
    "HOUSTON-AMER03",
    "SHANGHAI-APAC02",
]


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


def code_required() -> bool:
    """Signup is open unless a deployment sets a code."""
    return bool(signup_code())


def code_ok(supplied: str) -> bool:
    expected = signup_code()
    if not expected:
        return True          # no code configured: signup is open
    return secrets.compare_digest(supplied or "", expected)


def password_problems(password: str) -> list[str]:
    """What the password is still missing, in the words the form shows."""
    password = password or ""
    problems = []
    if len(password) < MIN_PASSWORD:
        problems.append(i18n.t("at least {n} characters", n=MIN_PASSWORD))
    if not re.search(r"[A-Z]", password):
        problems.append(i18n.t("an uppercase letter"))
    if not re.search(r"[0-9]", password):
        problems.append(i18n.t("a number"))
    if not re.search(r"[^A-Za-z0-9]", password):
        problems.append(i18n.t("a symbol"))
    return problems


def require_login() -> bool:
    """Everything needs an account. Set SDOC_REQUIRE_LOGIN=0 to open reading.

    Signup being open is what makes this reasonable: nobody is locked out,
    they just make an account first, the way any mail service works.
    """
    return os.environ.get("SDOC_REQUIRE_LOGIN", "1") == "1"


def normalise(email: str) -> str:
    return (email or "").strip().lower()


def create_user(email: str, password: str, out_dir: Path | None = None,
                name: str = "", desk: str = "", confirm: str | None = None) -> dict:
    """Caller checks the signup code. Raises ValueError with a message meant
    to be read by the person who typed it."""
    email = normalise(email)
    if not (name or "").strip():
        raise ValueError(i18n.t("your name is required"))
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ValueError(i18n.t("that does not look like an email address"))
    problems = password_problems(password)
    if problems:
        raise ValueError(i18n.t("password needs {items}", items=", ".join(problems)))
    if confirm is not None and password != confirm:
        raise ValueError(i18n.t("the two passwords do not match"))
    if desk and desk not in DESKS:
        raise ValueError(i18n.t("pick a desk from the list"))
    users = load_users(out_dir)
    if email in users:
        raise ValueError(i18n.t("an account with that email already exists"))
    users[email] = {
        "email": email,
        "name": name.strip(),
        "desk": desk or "",
        "password": hash_password(password),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_users(users, out_dir)
    return users[email]


def get_user(email: str, out_dir: Path | None = None) -> dict | None:
    return load_users(out_dir).get(normalise(email))


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
