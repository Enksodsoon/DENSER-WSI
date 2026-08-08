from __future__ import annotations

import hashlib
import hmac


def redact_source_identifier(value: str, salt: bytes) -> str:
    if len(salt) < 16:
        raise ValueError("salt must contain at least 16 bytes")
    if not value:
        raise ValueError("value must not be empty")
    digest = hmac.new(salt, value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"src_{digest[:24]}"
