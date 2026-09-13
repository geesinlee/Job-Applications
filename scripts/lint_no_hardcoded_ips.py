#!/usr/bin/env python3
"""
Governance linter: Check for hardcoded intranet/LAN IP literals in configs & source code.

Ensures zero-LAN-IP exposure prior to exposing applications to internet/ingress.
Requires using Tailscale MagicDNS (*.ts.net), canonical hostnames, or parameterized env variables.
"""

import os
import re
import sys
from pathlib import Path

FORBIDDEN_PATTERNS = [
    (re.compile(r"https?://192\.168\.[0-9]+\.[0-9]+(?::[0-9]+)?"), "Raw LAN HTTP/HTTPS IP"),
    (re.compile(r"https?://100\.[0-9]+\.[0-9]+\.[0-9]+(?::[0-9]+)?"), "Raw Tailscale HTTP/HTTPS IP (use MagicDNS *.ts.net)"),
    (re.compile(r"\b192\.168\.10\.[0-9]+\b"), "Intranet LAN IP literal"),
]

EXCLUDED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "scratch", "dist", "build", "temp-trash", "superpowers", "archive"}
EXCLUDED_FILES = {"CLAUDE.md", "AGENTS.md", "security.md", "boundaries.md", "caveman.md"}


def check_directory(base_dir: Path) -> list[dict]:
    violations = []
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for file in files:
            if file in EXCLUDED_FILES:
                continue
            file_path = Path(root) / file
            if file.startswith(".") and not file.startswith(".env"):
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                for line_no, line in enumerate(content.splitlines(), start=1):
                    stripped = line.strip()
                    if (file.endswith(".md") or "example" in file.lower()) and (
                        stripped.startswith("#") or "sample" in stripped.lower()
                    ):
                        continue

                    for pattern, desc in FORBIDDEN_PATTERNS:
                        matches = pattern.findall(line)
                        if matches:
                            if "192.168.10.0/24" in line:
                                continue
                            violations.append({
                                "file": str(file_path.relative_to(base_dir)),
                                "line": line_no,
                                "match": matches[0],
                                "desc": desc,
                                "snippet": stripped,
                            })
            except Exception:
                pass
    return violations


def main():
    repo_root = Path(__file__).resolve().parent.parent
    violations = check_directory(repo_root)

    if violations:
        print(f"\n❌ FAILED: Found {len(violations)} hardcoded LAN IP violations:")
        for v in violations:
            print(f"  - {v['file']}:{v['line']} [{v['desc']}]: {v['snippet']}")
        print("\nUse canonical mDNS (rv-cloud.local), Tailscale MagicDNS (*.ts.net), or env variables.")
        sys.exit(1)
    else:
        print("✅ PASSED: Zero hardcoded LAN IPs detected.")
        sys.exit(0)


if __name__ == "__main__":
    main()
