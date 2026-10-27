from __future__ import annotations

import keyring
import keyring.backend
import pytest


class InMemoryKeyring(keyring.backend.KeyringBackend):

    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self._store: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self._store:
            raise keyring.errors.PasswordDeleteError(
                f"no entry for {service}/{username}"
            )
        del self._store[(service, username)]


@pytest.fixture
def memory_keyring(monkeypatch: pytest.MonkeyPatch) -> InMemoryKeyring:
    backend = InMemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    return backend
