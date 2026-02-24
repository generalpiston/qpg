from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SENSITIVE_KEYS = {"password", "passwd", "pwd", "token", "secret", "apikey", "api_key"}


def redact_dsn(dsn: str) -> str:
    parts = urlsplit(dsn)
    if not parts.scheme or not parts.netloc:
        return dsn

    netloc = parts.netloc
    if "@" in netloc:
        userinfo, hostinfo = netloc.rsplit("@", 1)
        if ":" in userinfo:
            username, _ = userinfo.split(":", 1)
            userinfo = f"{username}:***"
        netloc = f"{userinfo}@{hostinfo}"

    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in SENSITIVE_KEYS:
            query_pairs.append((key, "***"))
        else:
            query_pairs.append((key, value))

    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query_pairs), parts.fragment))


def redact_secret(secret: str | None, *, keep_prefix: int = 3, keep_suffix: int = 2) -> str | None:
    if secret is None:
        return None
    if not secret:
        return ""
    if keep_prefix < 0 or keep_suffix < 0:
        raise ValueError("keep_prefix and keep_suffix must be non-negative")

    visible = keep_prefix + keep_suffix
    if len(secret) <= visible:
        return "*" * len(secret)
    return f"{secret[:keep_prefix]}...{secret[-keep_suffix:]}"
