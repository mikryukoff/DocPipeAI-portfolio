from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


class FileEncryptionService:
    def __init__(self, key: str):
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        fernet_key = base64.urlsafe_b64encode(digest)
        self._fernet = Fernet(fernet_key)

    def encrypt(self, payload: bytes) -> bytes:
        return self._fernet.encrypt(payload)

    def decrypt(self, payload: bytes) -> bytes:
        return self._fernet.decrypt(payload)
