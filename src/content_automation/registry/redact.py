"""Redaction for the audit log (PRD D9): nothing secret is ever written to an event.

Three layers, applied to every string (also inside lists and dicts):
1. Secret values from the environment and .env: the value of every variable whose name has a
   KEY, TOKEN, SECRET, PASSWORD, CREDENTIAL(S), AUTH or COOKIE part (OPENROUTER_API_KEY,
   GOOGLE_* ...). Other .env values (IMAGE_PROVIDER=openrouter) are not secret and
   stay readable.
2. Token- and key-like strings: sk-..., Bearer/Basic ..., known key prefixes (rpa_, hf_, ghp_,
   ya29., 1//0, GOCSPX-, AIza), JWTs, long hex (32+) and long random base64 (40+, mixed case
   and digits; lowercase paths and slugs stay).
3. OAuth/key fields: a dict key such as client_secret, refresh_token, access_token, api_key or
   password has its whole value replaced; the same fields inside JSON text too.
A hex value under a hash-named key (idempotency_key, sha256, csv_hash) is kept: it is not secret.
"""

import os
import re
from collections.abc import Mapping
from pathlib import Path, PurePath
from typing import Any

from dotenv import dotenv_values

REDACTED = "[redacted]"
DEFAULT_ENV_FILE = Path(".env")
MIN_SECRET_LENGTH = 8  # shorter environment values are too common to replace everywhere
SECRET_NAME_PARTS = frozenset({
    "KEY", "KEYS", "APIKEY", "TOKEN", "TOKENS", "SECRET", "SECRETS", "PASSWORD", "PASSWD",
    "CREDENTIAL", "CREDENTIALS", "AUTH", "COOKIE",
})

_SECRET_FIELD = re.compile(
    r"(?:.*_)?(?:client_secret|secret|refresh_token|access_token|id_token|token|api_?key"
    r"|access_key|secret_key|private_key|password|passwd|authorization|credentials?|cookie)"
)
_HASH_FIELD = re.compile(r"(?:.*_)?(?:hash|sha1|sha256|checksum|digest|idempotency_key|etag)")
_HEX = re.compile(r"[0-9a-fA-F]+")
_OAUTH_JSON = re.compile(
    r'("(?:client_secret|refresh_token|access_token|id_token|private_key|api_key|apikey'
    r'|password)"\s*:\s*")[^"]*(")',
    re.IGNORECASE,
)
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_OAUTH_JSON, rf"\g<1>{REDACTED}\g<2>"),
    (re.compile(r"\b([A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD))(\s*[=:]\s*)(?!\[redacted\])"
                r"[^\s,;\"']{8,}", re.IGNORECASE), rf"\g<1>\g<2>{REDACTED}"),
    (re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=\-]{8,}", re.IGNORECASE),
     rf"\g<1> {REDACTED}"),
    (re.compile(r"\bsk[-_][A-Za-z0-9_\-]{8,}"), REDACTED),
    (re.compile(r"\b(?:rpa|hf|ghp|gho|ghu|ghs|ghr|glpat|xox[abprs])[-_][A-Za-z0-9_\-]{10,}"),
     REDACTED),
    (re.compile(r"\bya29\.[A-Za-z0-9._\-]+"), REDACTED),
    (re.compile(r"\b1//0[A-Za-z0-9_\-]{20,}"), REDACTED),
    (re.compile(r"\bGOCSPX-[A-Za-z0-9_\-]{10,}"), REDACTED),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), REDACTED),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]*"), REDACTED),
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), REDACTED),
)
_BASE64ISH = re.compile(r"(?<![A-Za-z0-9+/_\-])[A-Za-z0-9+/_\-]{40,}={0,2}")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _secret_name(name: str) -> bool:
    return any(part in SECRET_NAME_PARTS for part in re.split(r"[^A-Z0-9]+", name.upper()))


def secret_values(
    env_file: Path | None = DEFAULT_ENV_FILE, environ: Mapping[str, str] | None = None
) -> frozenset[str]:
    """The values of secret-named variables in the environment and the .env file."""
    pairs: list[tuple[str, str]] = list((os.environ if environ is None else environ).items())
    if env_file is not None and env_file.is_file():
        pairs += [(name, value) for name, value in dotenv_values(env_file).items() if value]
    return frozenset(
        value.strip() for name, value in pairs
        if _secret_name(name) and len(value.strip()) >= MIN_SECRET_LENGTH
    )


def _random_looking(match: re.Match[str]) -> str:
    text = match.group(0)
    core = text.rstrip("=")
    mixed = (any(c.isupper() for c in core) and any(c.islower() for c in core)
             and any(c.isdigit() for c in core))
    words = [part for part in re.split(r"[/_\-]", core) if len(part) >= 4]
    plain = any(part.isalpha() and part.islower() for part in words)  # paths and slugs
    return REDACTED if mixed and not plain else text


def redact_text(text: str, secrets: frozenset[str] | None = None) -> str:
    """`text` with every secret value and token-like string replaced by [redacted]."""
    for secret in sorted(secret_values() if secrets is None else secrets, key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return _BASE64ISH.sub(_random_looking, text)


def _field(name: str) -> str:
    return _CAMEL.sub("_", name).lower()


def _walk(value: Any, secrets: frozenset[str], key: str | None) -> Any:
    if isinstance(value, Mapping):
        return {
            str(name): REDACTED if _SECRET_FIELD.fullmatch(_field(str(name))) and item
            else _walk(item, secrets, str(name))
            for name, item in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [_walk(item, secrets, key) for item in value]
    if isinstance(value, bool | int | float) or value is None:
        return value
    text = value.as_posix() if isinstance(value, PurePath) else str(value)
    if key is not None and _HASH_FIELD.fullmatch(_field(key)) and _HEX.fullmatch(text):
        return text
    return redact_text(text, secrets)


def redact_data(value: Any, secrets: frozenset[str] | None = None) -> Any:
    """A JSON-ready copy of `value` with secrets removed (paths as POSIX text, other objects
    as str)."""
    return _walk(value, secret_values() if secrets is None else secrets, None)
