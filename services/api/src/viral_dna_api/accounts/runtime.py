from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..runtime_config import get_config_value
from ..workspace_catalog import default_account_catalog_path
from .repository import AccountRepository


def password_auth_enabled() -> bool:
    return get_config_value("VIRAL_DNA_AUTH_MODE", "password").strip().lower() == "password"


@lru_cache(maxsize=8)
def _repository(path: str, tenant_root: str) -> AccountRepository:
    return AccountRepository(Path(path), Path(tenant_root))


def account_repository() -> AccountRepository:
    base = default_account_catalog_path().parent
    path = str(account_database_path())
    root = get_config_value("VIRAL_DNA_ACCOUNTS_ROOT", "").strip() or str(base / "accounts")
    return _repository(path, root)


def account_database_path() -> Path:
    """Resolve without opening/initializing the database, for the startup lock."""
    configured = get_config_value("VIRAL_DNA_AUTH_DB_PATH", "").strip()
    return (
        Path(configured).resolve()
        if configured
        else (default_account_catalog_path().parent / "accounts.sqlite3")
    )
