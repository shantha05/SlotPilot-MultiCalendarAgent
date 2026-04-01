"""Persistent storage for MSAL token cache and account metadata.

Stores encrypted token cache and account information in the user's home
directory so accounts persist across app restarts and browser sessions.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from observability.logger import get_logger

log = get_logger(__name__)

# Storage location in user's home directory
STORAGE_DIR = Path.home() / ".slotpilot"
CACHE_FILE = STORAGE_DIR / "token_cache.json"
ACCOUNTS_FILE = STORAGE_DIR / "accounts.json"


def _ensure_storage_dir() -> None:
    """Create storage directory if it doesn't exist with restricted permissions."""
    if not STORAGE_DIR.exists():
        STORAGE_DIR.mkdir(mode=0o700, parents=True)
        log.info("Created storage directory", extra={"path": str(STORAGE_DIR)})


def save_token_cache(cache_str: str) -> None:
    """Save MSAL token cache to disk.
    
    Args:
        cache_str: Serialized token cache string from MSAL.
    """
    try:
        _ensure_storage_dir()
        CACHE_FILE.write_text(cache_str, encoding="utf-8")
        # Set restrictive permissions (user read/write only)
        if os.name != "nt":  # Unix-like systems
            os.chmod(CACHE_FILE, 0o600)
        log.debug("Token cache saved to disk")
    except Exception as exc:
        log.error("Failed to save token cache", extra={"error": str(exc)})


def load_token_cache() -> Optional[str]:
    """Load MSAL token cache from disk.
    
    Returns:
        Serialized cache string or None if file doesn't exist.
    """
    try:
        if CACHE_FILE.exists():
            cache_str = CACHE_FILE.read_text(encoding="utf-8")
            log.debug("Token cache loaded from disk")
            return cache_str
    except Exception as exc:
        log.error("Failed to load token cache", extra={"error": str(exc)})
    return None


def save_accounts(accounts: dict) -> None:
    """Save account metadata to disk.
    
    Args:
        accounts: Dict of {label: {"email": str}} from session state.
    """
    try:
        _ensure_storage_dir()
        # Only save email addresses, not MSAL account objects
        accounts_data = {
            label: {"email": info.get("email", "")}
            for label, info in accounts.items()
        }
        ACCOUNTS_FILE.write_text(
            json.dumps(accounts_data, indent=2),
            encoding="utf-8"
        )
        # Set restrictive permissions (user read/write only)
        if os.name != "nt":  # Unix-like systems
            os.chmod(ACCOUNTS_FILE, 0o600)
        log.debug("Accounts saved to disk", extra={"count": len(accounts)})
    except Exception as exc:
        log.error("Failed to save accounts", extra={"error": str(exc)})


def load_accounts() -> dict:
    """Load account metadata from disk.
    
    Returns:
        Dict of {label: {"email": str}} or empty dict if file doesn't exist.
    """
    try:
        if ACCOUNTS_FILE.exists():
            accounts_data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
            log.debug("Accounts loaded from disk", extra={"count": len(accounts_data)})
            return accounts_data
    except Exception as exc:
        log.error("Failed to load accounts", extra={"error": str(exc)})
    return {}


def clear_all_storage() -> None:
    """Remove all persisted data (useful for debugging or factory reset)."""
    try:
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
            log.info("Token cache deleted")
        if ACCOUNTS_FILE.exists():
            ACCOUNTS_FILE.unlink()
            log.info("Accounts file deleted")
        if STORAGE_DIR.exists() and not list(STORAGE_DIR.iterdir()):
            STORAGE_DIR.rmdir()
            log.info("Storage directory removed")
    except Exception as exc:
        log.error("Failed to clear storage", extra={"error": str(exc)})
