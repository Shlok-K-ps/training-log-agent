"""Small shared encryption boundary for sensitive integration data."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class SecretCipherError(RuntimeError):
    pass


class SecretCipher:
    def __init__(self, key: str) -> None:
        if not key:
            raise SecretCipherError("an integration encryption key is not configured")
        try:
            self._fernet = Fernet(key.encode())
        except (ValueError, TypeError) as exc:
            raise SecretCipherError("the integration encryption key is invalid") from exc

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise SecretCipherError("encrypted integration data could not be decrypted") from exc
