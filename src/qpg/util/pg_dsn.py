from __future__ import annotations

import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

READONLY_OPTION = "-c default_transaction_read_only=on"
READONLY_ON_PATTERN = re.compile(
    r"(?:^|\s)-c\s*default_transaction_read_only\s*=\s*on(?:\s|$)",
    re.IGNORECASE,
)


def _merge_options(values: list[str]) -> str:
    parts = [value.strip() for value in values if value.strip()]
    merged = " ".join(parts)
    if READONLY_ON_PATTERN.search(merged):
        return merged
    if merged:
        return f"{merged} {READONLY_OPTION}"
    return READONLY_OPTION


def enforce_readonly_dsn(dsn: str) -> str:
    parts = urlsplit(dsn)
    if parts.scheme not in {"postgres", "postgresql"} or not parts.netloc:
        return dsn

    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    options_values: list[str] = []
    passthrough_pairs: list[tuple[str, str]] = []

    for key, value in query_pairs:
        if key.lower() == "options":
            options_values.append(value)
        else:
            passthrough_pairs.append((key, value))

    passthrough_pairs.append(("options", _merge_options(options_values)))
    query = urlencode(passthrough_pairs, doseq=True, quote_via=quote)

    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def dsn_has_password(dsn: str) -> bool:
    parts = urlsplit(dsn)
    if parts.scheme not in {"postgres", "postgresql"} or not parts.netloc or "@" not in parts.netloc:
        return False
    userinfo, _ = parts.netloc.rsplit("@", 1)
    if ":" not in userinfo:
        return False
    _, password = userinfo.split(":", 1)
    return bool(password)


def dsn_with_password(dsn: str, password: str) -> str:
    parts = urlsplit(dsn)
    if parts.scheme not in {"postgres", "postgresql"} or not parts.netloc or "@" not in parts.netloc:
        return dsn

    userinfo, hostinfo = parts.netloc.rsplit("@", 1)
    username = userinfo.split(":", 1)[0]
    encoded_password = quote(password, safe="")
    netloc = f"{username}:{encoded_password}@{hostinfo}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
