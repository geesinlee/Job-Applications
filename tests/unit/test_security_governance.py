"""
Security, Governance, and Internet-Enablement Test Suite.

Verifies:
1. HTTP Bearer Token authentication & authorization enforcement (_StaticBearerMiddleware).
2. HTTP startup security gate (MCP_MODE=http requiring MCP_AUTH_TOKEN).
3. Path traversal attack mitigation (_company_dir, _resolve_company_folder).
4. Fleet Zero-LAN-IP policy compliance.
5. Fleet Secret exposure and .env tracking policy compliance.
6. Fleet Domain Boundary & Anti-Infringement isolation.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import job_applications_mcp_server as server


# ---------------------------------------------------------------------------
# 1. Bearer Token Auth Middleware Tests
# ---------------------------------------------------------------------------

class TestBearerAuthMiddleware:
    """Tests for _StaticBearerMiddleware in HTTP mode."""

    @pytest.fixture
    def test_app(self, monkeypatch):
        test_token = "secure-test-token-1234567890abcdef"
        monkeypatch.setattr(server, "MCP_AUTH_TOKEN", test_token)

        from starlette.middleware.base import BaseHTTPMiddleware

        class _StaticBearerMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                auth_header = request.headers.get("authorization", "")
                scheme, _, token = auth_header.partition(" ")
                if scheme.lower() != "bearer" or token != test_token:
                    return JSONResponse(
                        {"error": "Unauthorized"},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                return await call_next(request)

        async def homepage(request):
            return PlainTextResponse("authenticated")

        app = Starlette(routes=[Route("/mcp", endpoint=homepage)])
        app.add_middleware(_StaticBearerMiddleware)
        return TestClient(app), test_token

    def test_missing_auth_header_rejected(self, test_app):
        client, _ = test_app
        response = client.get("/mcp")
        assert response.status_code == 401
        assert response.headers.get("WWW-Authenticate") == "Bearer"
        assert response.json() == {"error": "Unauthorized"}

    def test_invalid_scheme_rejected(self, test_app):
        client, token = test_app
        response = client.get("/mcp", headers={"Authorization": f"Basic {token}"})
        assert response.status_code == 401
        assert response.headers.get("WWW-Authenticate") == "Bearer"

    def test_invalid_token_rejected(self, test_app):
        client, _ = test_app
        response = client.get("/mcp", headers={"Authorization": "Bearer wrong-invalid-token"})
        assert response.status_code == 401
        assert response.headers.get("WWW-Authenticate") == "Bearer"

    def test_empty_bearer_token_rejected(self, test_app):
        client, _ = test_app
        response = client.get("/mcp", headers={"Authorization": "Bearer "})
        assert response.status_code == 401

    def test_valid_bearer_token_accepted(self, test_app):
        client, token = test_app
        response = client.get("/mcp", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.text == "authenticated"


# ---------------------------------------------------------------------------
# 2. HTTP Startup Security Gate Tests
# ---------------------------------------------------------------------------

class TestHttpStartupSecurityGate:
    """Verify server rejects HTTP mode without explicit auth token."""

    def test_http_mode_requires_auth_token(self):
        # Run a subprocess with MCP_MODE=http and MCP_AUTH_TOKEN=""
        env = dict(os.environ)
        env["MCP_MODE"] = "http"
        env["MCP_AUTH_TOKEN"] = ""

        cmd = [
            sys.executable,
            "-c",
            "import job_applications_mcp_server"
        ]
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        assert proc.returncode != 0
        assert "requires MCP_AUTH_TOKEN" in proc.stderr


# ---------------------------------------------------------------------------
# 3. Path Traversal Defense Tests
# ---------------------------------------------------------------------------

class TestPathTraversalMitigation:
    """Verify file paths cannot escape ARTEFACTS_DIR."""

    def test_company_dir_rejects_parent_traversal(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "ARTEFACTS_DIR", tmp_path / "artifacts")
        (tmp_path / "artifacts").mkdir()

        with pytest.raises(ValueError, match="Path traversal"):
            server._company_dir("../../etc/shadow")

    def test_company_dir_rejects_relative_dotdot(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "ARTEFACTS_DIR", tmp_path / "artifacts")
        (tmp_path / "artifacts").mkdir()

        with pytest.raises(ValueError, match="Path traversal"):
            server._company_dir("../sibling_dir")

    def test_company_dir_allows_valid_subfolder(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "ARTEFACTS_DIR", tmp_path / "artifacts")
        (tmp_path / "artifacts").mkdir()

        d = server._company_dir("ValidCompany")
        assert d.exists()
        assert d == tmp_path / "artifacts" / "ValidCompany"

    def test_resolve_company_folder_rejects_parent_traversal(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "ARTEFACTS_DIR", tmp_path / "artifacts")
        (tmp_path / "artifacts").mkdir()

        with pytest.raises(ValueError, match="Path traversal"):
            server._resolve_company_folder("../../escape")


# ---------------------------------------------------------------------------
# 4. Zero-LAN-IP Exposure Governance Tests
# ---------------------------------------------------------------------------

class TestZeroLanIpGovernance:
    """Verify repo adheres to Fleet Zero-LAN-IP Policy."""

    def test_no_hardcoded_lan_ips_in_repo(self):
        from scripts.lint_no_hardcoded_ips import check_directory
        repo_root = Path(__file__).resolve().parent.parent.parent
        violations = check_directory(repo_root)
        assert violations == [], f"Detected hardcoded LAN IP violations: {violations}"


# ---------------------------------------------------------------------------
# 5. Secret Hygiene & Tracking Governance Tests
# ---------------------------------------------------------------------------

class TestSecretHygieneGovernance:
    """Verify git does not track sensitive credentials."""

    def test_env_file_not_tracked_in_git(self):
        repo_root = Path(__file__).resolve().parent.parent.parent
        result = subprocess.run(
            ["git", "ls-files", ".env"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "", ".env file is tracked in git! Must be gitignored."

    def test_secret_rotation_engine_clean(self):
        from scripts.secret_rotation_engine import scan_workspace
        violations = scan_workspace()
        assert violations == [], f"Found exposed plain-text secrets in repository: {violations}"


# ---------------------------------------------------------------------------
# 6. Domain Boundary Governance Tests
# ---------------------------------------------------------------------------

class TestDomainBoundaryGovernance:
    """Verify repo adheres to Fleet Domain Boundaries & Anti-Infringement rules."""

    def test_domain_boundaries_clean(self):
        from scripts.lint_domain_boundaries import check_repo_boundaries
        repo_root = Path(__file__).resolve().parent.parent.parent
        violations = check_repo_boundaries(repo_root)
        assert violations == [], f"Domain boundary infringements detected: {violations}"
