#!/usr/bin/env python3
"""Job Applications MCP Server — Orchestrates job application workflow.

Manages company folders, job description parsing, research templates,
territory mapping, and document generation for job applications.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

mcp = FastMCP("job-applications")

# Base directory: the Job-Applications folder containing company subfolders
BASE_DIR = Path(__file__).resolve().parent


def _company_dir(company: str) -> Path:
    """Return the path to a company folder, creating it if needed."""
    d = BASE_DIR / company
    d.mkdir(parents=True, exist_ok=True)
    return d


def _extract_pdf_text(pdf_path: Path) -> str:
    """Extract text from a PDF file."""
    if PdfReader is None:
        return "[ERROR: PyPDF2 not installed. Install with: pip install PyPDF2]"
    reader = PdfReader(str(pdf_path))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n\n".join(pages)


def _read_file(path: Path) -> str | None:
    """Read a text file, returning None if it doesn't exist."""
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _find_cv(company_dir: Path) -> Path | None:
    """Find the CV file in a company folder (PDF or Markdown)."""
    for pattern in ["CV*.pdf", "CV*.md", "cv*.pdf", "cv*.md", "Resume*.pdf", "Resume*.md"]:
        matches = list(company_dir.glob(pattern))
        if matches:
            return matches[0]
    # Also check for exact-name CV files
    for f in company_dir.iterdir():
        if f.is_file() and "cv" in f.name.lower() and f.suffix in (".pdf", ".md"):
            return f
    return None


# ... tools will be added here ...