"""Tests for gmail_auth module — Gmail OAuth2 authentication."""

from __future__ import annotations

import json
import time
from pathlib import Path

from unittest.mock import Mock

import pytest

from gmail_auth import AccountConfig, GmailAccountManager, VALID_CATEGORIES


# ---------------------------------------------------------------------------
# AccountConfig.from_dict
# ---------------------------------------------------------------------------

class TestAccountConfig:
    def test_from_dict_all_fields(self):
        data = {
            "email": "alice@gmail.com",
            "category": "work",
            "client_id": "cid",
            "client_secret": "csec",
            "refresh_token": "rtok",
        }
        cfg = AccountConfig.from_dict("personal_acct", data)
        assert cfg.key == "personal_acct"
        assert cfg.email == "alice@gmail.com"
        assert cfg.category == "work"
        assert cfg.client_id == "cid"
        assert cfg.client_secret == "csec"
        assert cfg.refresh_token == "rtok"
        assert cfg.credentials_file == ""

    def test_from_dict_defaults(self):
        """Missing fields default to empty strings; category defaults to personal."""
        cfg = AccountConfig.from_dict("acct1", {"email": "bob@gmail.com"})
        assert cfg.email == "bob@gmail.com"
        assert cfg.category == "personal"
        assert cfg.client_id == ""
        assert cfg.client_secret == ""
        assert cfg.refresh_token == ""
        assert cfg.credentials_file == ""

    def test_from_dict_invalid_category_falls_back(self):
        """An invalid category value falls back to 'personal'."""
        data = {"email": "x@x.com", "category": "unknown_cat"}
        cfg = AccountConfig.from_dict("acct", data)
        assert cfg.category == "personal"

    def test_from_dict_credentials_file_field(self):
        data = {
            "email": "a@b.com",
            "credentials_file": "/path/to/creds.json",
        }
        cfg = AccountConfig.from_dict("acct", data)
        assert cfg.credentials_file == "/path/to/creds.json"


# ---------------------------------------------------------------------------
# GmailAccountManager
# ---------------------------------------------------------------------------

class TestGmailAccountManager:
    def _write_config(self, tmp_path: Path, accounts: dict, cred_files: dict | None = None):
        """Helper: write gmail_accounts.json and optional credential files.

        accounts: dict keyed by account key -> dict of account fields
        cred_files: dict keyed by account key -> dict of credential fields
                    (client_id, client_secret, refresh_token)
        """
        cred_files = cred_files or {}
        # Write per-account credential files
        for key, creds in cred_files.items():
            cred_path = tmp_path / f"creds_{key}.json"
            cred_path.write_text(json.dumps(creds), encoding="utf-8")
            # Inject credentials_file path into account data
            accounts[key]["credentials_file"] = str(cred_path)

        config_path = tmp_path / "gmail_accounts.json"
        config_path.write_text(json.dumps({"accounts": accounts}), encoding="utf-8")
        return str(config_path)

    def test_load_config_with_credentials(self, tmp_path):
        cred_files = {
            "personal_acct": {
                "client_id": "cid1",
                "client_secret": "csec1",
                "refresh_token": "rtok1",
            }
        }
        accounts = {
            "personal_acct": {
                "email": "alice@gmail.com",
                "category": "personal",
            }
        }
        config_path = self._write_config(tmp_path, accounts, cred_files)
        mgr = GmailAccountManager(config_path)

        assert "personal_acct" in mgr.accounts
        acct = mgr.accounts["personal_acct"]
        assert acct.email == "alice@gmail.com"
        assert acct.category == "personal"
        assert acct.client_id == "cid1"
        assert acct.client_secret == "csec1"
        assert acct.refresh_token == "rtok1"

    def test_get_access_token_refreshes(self, tmp_path, monkeypatch):
        """get_access_token calls the token endpoint and returns an access token."""
        cred_files = {
            "personal_acct": {
                "client_id": "cid1",
                "client_secret": "csec1",
                "refresh_token": "rtok1",
            }
        }
        accounts = {
            "personal_acct": {
                "email": "alice@gmail.com",
                "category": "personal",
            }
        }
        config_path = self._write_config(tmp_path, accounts, cred_files)
        mgr = GmailAccountManager(config_path)

        mock_response = Mock()
        mock_response.json.return_value = {"access_token": "at_123", "expires_in": 3600}
        mock_response.raise_for_status = Mock()

        monkeypatch.setattr("gmail_auth.requests.post", lambda *a, **kw: mock_response)

        token = mgr.get_access_token("personal_acct")
        assert token == "at_123"
        mock_response.raise_for_status.assert_called_once()

    def test_get_access_token_uses_cache(self, tmp_path, monkeypatch):
        """Second call within the expiry window returns cached token without POST."""
        cred_files = {
            "personal_acct": {
                "client_id": "cid1",
                "client_secret": "csec1",
                "refresh_token": "rtok1",
            }
        }
        accounts = {
            "personal_acct": {
                "email": "alice@gmail.com",
                "category": "personal",
            }
        }
        config_path = self._write_config(tmp_path, accounts, cred_files)
        mgr = GmailAccountManager(config_path)

        call_count = 0

        def mock_post(url, data=None, timeout=None):
            nonlocal call_count
            call_count += 1
            r = Mock()
            r.json.return_value = {"access_token": "at_cached", "expires_in": 3600}
            r.raise_for_status = Mock()
            return r

        monkeypatch.setattr("gmail_auth.requests.post", mock_post)

        token1 = mgr.get_access_token("personal_acct")
        token2 = mgr.get_access_token("personal_acct")
        assert token1 == "at_cached"
        assert token2 == "at_cached"
        assert call_count == 1  # Only one POST; second call hit cache

    def test_get_access_token_missing_account_returns_none(self, tmp_path):
        """Requesting a token for an unknown account returns None."""
        config_path = self._write_config(tmp_path, {})
        mgr = GmailAccountManager(config_path)

        result = mgr.get_access_token("unknown_acct")
        assert result is None

    def test_get_access_token_network_error_returns_none(self, tmp_path, monkeypatch):
        """Network failure during token refresh returns None."""
        import requests

        cred_files = {
            "personal_acct": {
                "client_id": "cid1",
                "client_secret": "csec1",
                "refresh_token": "rtok1",
            }
        }
        accounts = {
            "personal_acct": {
                "email": "alice@gmail.com",
                "category": "personal",
            }
        }
        config_path = self._write_config(tmp_path, accounts, cred_files)
        mgr = GmailAccountManager(config_path)

        def mock_post_raises(*a, **kw):
            raise requests.RequestException("connection error")

        monkeypatch.setattr("gmail_auth.requests.post", mock_post_raises)

        result = mgr.get_access_token("personal_acct")
        assert result is None

    def test_get_access_token_missing_access_token_in_response_returns_none(self, tmp_path, monkeypatch):
        """Token response without access_token returns None."""
        cred_files = {
            "personal_acct": {
                "client_id": "cid1",
                "client_secret": "csec1",
                "refresh_token": "rtok1",
            }
        }
        accounts = {
            "personal_acct": {
                "email": "alice@gmail.com",
                "category": "personal",
            }
        }
        config_path = self._write_config(tmp_path, accounts, cred_files)
        mgr = GmailAccountManager(config_path)

        mock_response = Mock()
        mock_response.json.return_value = {"expires_in": 3600}  # no access_token
        mock_response.raise_for_status = Mock()

        monkeypatch.setattr("gmail_auth.requests.post", lambda *a, **kw: mock_response)

        result = mgr.get_access_token("personal_acct")
        assert result is None

    def test_missing_config_file_logs_warning(self, tmp_path, caplog):
        """A missing config file logs a warning and creates an empty manager."""
        missing_path = str(tmp_path / "nonexistent_gmail_accounts.json")
        import logging
        with caplog.at_level(logging.WARNING):
            mgr = GmailAccountManager(missing_path)

        assert len(mgr.accounts) == 0
        assert "not found" in caplog.text.lower() or "config file" in caplog.text.lower()

    def test_category_for(self, tmp_path):
        cred_files = {
            "work_acct": {
                "client_id": "cid2",
                "client_secret": "csec2",
                "refresh_token": "rtok2",
            }
        }
        accounts = {
            "work_acct": {
                "email": "bob@work.com",
                "category": "work",
            }
        }
        config_path = self._write_config(tmp_path, accounts, cred_files)
        mgr = GmailAccountManager(config_path)

        assert mgr.category_for("work_acct") == "work"
        assert mgr.category_for("nonexistent") == "personal"

    def test_account_for_category(self, tmp_path):
        cred_files = {
            "personal_acct": {
                "client_id": "cid1",
                "client_secret": "csec1",
                "refresh_token": "rtok1",
            }
        }
        accounts = {
            "personal_acct": {
                "email": "alice@gmail.com",
                "category": "personal",
            }
        }
        config_path = self._write_config(tmp_path, accounts, cred_files)
        mgr = GmailAccountManager(config_path)

        assert mgr.account_for_category("personal") == "personal_acct"
        assert mgr.account_for_category("work") is None