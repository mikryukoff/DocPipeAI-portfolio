from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

def generate_totp_secret() -> str:
    raw = secrets.token_bytes(20)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def get_totp_uri(*, username: str, secret: str, issuer: str) -> str:
    return (
        f"otpauth://totp/{quote(issuer)}:{quote(username)}"
        f"?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
    )


def verify_totp(*, secret: str, code: str) -> bool:
    if not code.isdigit():
        return False
    for offset in (-1, 0, 1):
        if _totp_now(secret=secret, step_offset=offset) == code.zfill(6):
            return True
    return False


def generate_qr_data_uri(uri: str) -> str:
    encoded = base64.b64encode(uri.encode("utf-8")).decode("ascii")
    return f"data:text/plain;base64,{encoded}"


def _totp_now(*, secret: str, step_offset: int = 0) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    counter = int(time.time() // 30) + step_offset
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    chunk = digest[offset:offset + 4]
    value = struct.unpack(">I", chunk)[0] & 0x7FFFFFFF
    return str(value % 1_000_000).zfill(6)
