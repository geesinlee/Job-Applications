"""OAuth2 authentication and multi-account management for Gmail API.

Supports reading email from multiple accounts configured in gmail_accounts.json.
Each account has a `provider` field (default "gmail") to prepare for future
support of Outlook, Yahoo, and Apple email providers.

For now, only "gmail" provider is implemented — others will raise an error
at auth time so they fail clearly rather than silently.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"personal", "work"}
VALID_PROVIDERS = {"gmail"}
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


@dataclass
class AccountConfig:
    key: str
    email: str
    category: str
    provider: str
    client_id: str
    client_secret: str
    refresh_token: str
    credentials_file: str

    @classmethod
    def from_dict(cls, key: str, data: dict) -> AccountConfig:
        return cls(
            key=key,
            email=data.get("email", ""),
            category=(
                data.get("category", "personal")
                if data.get("category", "personal") in VALID_CATEGORIES
                else "personal"
            ),
            provider=data.get("provider", "gmail"),
            client_id=data.get("client_id", ""),
            client_secret=data.get("client_secret", ""),
            refresh_token=data.get("refresh_token", ""),
            credentials_file=data.get("credentials_file", ""),
        )


class GmailAccountManager:
    """Loads Gmail account config and manages OAuth2 access tokens."""

    def __init__(self, config_path: str):
        self.accounts: dict[str, AccountConfig] = {}
        self._tokens: dict[str, dict] = {}
        self._load_config(config_path)

    def _load_config(self, config_path: str) -> None:
        path = Path(config_path)
        if not path.exists():
            logger.warning("Config file not found: %s", config_path)
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read config: %s", e)
            return

        for key, acct_data in data.get("accounts", {}).items():
            provider = acct_data.get("provider", "gmail")
            if provider not in VALID_PROVIDERS:
                logger.warning(
                    "Skipping account '%s': unsupported provider '%s' "
                    "(supported: %s). Add the provider to VALID_PROVIDERS "
                    "when implementing its auth flow.",
                    key, provider, ", ".join(sorted(VALID_PROVIDERS)),
                )
                continue
            creds_path = acct_data.get("credentials_file", "")
            creds = self._load_credentials(creds_path)
            if creds is None:
                logger.warning(
                    "Skipping account '%s': credentials file not found or invalid",
                    key,
                )
                continue
            combined = {**acct_data, **creds}
            self.accounts[key] = AccountConfig.from_dict(key, combined)

    def _load_credentials(self, path: str) -> dict | None:
        p = Path(path)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def get_access_token(self, account: str) -> str | None:
        """Return a valid access token, refreshing if needed.

        Returns None if the account is not configured or token refresh fails.
        """
        if account not in self.accounts:
            logger.warning("Unknown account: %s", account)
            return None

        cached = self._tokens.get(account)
        if cached and cached["expires_at"] > time.time():
            return cached["token"]

        acct = self.accounts[account]
        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "client_id": acct.client_id,
                    "client_secret": acct.client_secret,
                    "refresh_token": acct.refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=10,
            )
            resp.raise_for_status()
            token_data = resp.json()
        except requests.RequestException as e:
            logger.error("Token refresh failed for '%s': %s", account, e)
            return None

        access_token = token_data.get("access_token")
        if not access_token:
            logger.error("Token response missing access_token for account '%s'", account)
            return None

        self._tokens[account] = {
            "token": access_token,
            "expires_at": time.time() + token_data.get("expires_in", 3600) - 60,
        }
        return access_token

    def category_for(self, account: str) -> str:
        """Return the category for an account, defaulting to 'personal'."""
        acct = self.accounts.get(account)
        return acct.category if acct else "personal"

    def account_for_category(self, category: str) -> str | None:
        """Return the account key for a given category, or None."""
        for key, acct in self.accounts.items():
            if acct.category == category:
                return key
        return None