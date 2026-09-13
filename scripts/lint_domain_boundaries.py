#!/usr/bin/env python3
"""
Domain Boundary & Anti-Infringement Linter
Scans fleet repositories to ensure:
1. Domain Boundary Policy is installed in AGENTS.md / CLAUDE.md / .agents/rules/boundaries.md.
2. Repositories do not infringe or duplicate foreign domain code (e.g. ad-hoc vector math outside Work-RAG).
"""

import re
import sys
import argparse
from pathlib import Path
from typing import List, Tuple, Dict, Any

# Pattern checks for foreign domain infringement
INFRINGEMENT_PATTERNS = [
    {
        "domain": "Work-RAG (Vector & Embeddings)",
        "allowed_repos": ["Work-RAG", "Work-RAG-SaaS", "fleet-rationalization"],
        "regex": r"(CREATE\s+EXTENSION.*vector|vector\s*\(\s*\d+\s*\)|cosine_similarity\(|dot_product\(|sentence_transformers)",
        "message": "Detected foreign vector embedding/pgvector implementation. Must consume via Work-RAG MCP or delegate."
    },
    {
        "domain": "Contact-Mgmt (SGDI & Contact Directory)",
        "allowed_repos": ["Contact-Mgmt", "contact-messages2", "fleet-rationalization"],
        "regex": r"(scrape_sgdi|sgdi\.gov\.sg/api|parse_vcf_directory)",
        "message": "Detected foreign SGDI/contact directory scraping. Must consume via Contact-Mgmt MCP."
    },
    {
        "domain": "fleet-rationalization (JIT Secret Leasing)",
        "allowed_repos": ["fleet-rationalization"],
        "regex": r"(def\s+lease_secret|class\s+SecretBroker|auto_vacuum_engine)",
        "message": "Detected foreign secret leasing or fleet maintenance logic. Must consume via Secret Broker MCP."
    }
]

def check_repo_boundaries(repo_dir: Path) -> List[Dict[str, Any]]:
    violations = []
    repo_name = repo_dir.name
    
    # 1. Check Policy presence
    has_policy = False
    for check_file in [repo_dir / ".agents" / "rules" / "boundaries.md", repo_dir / "AGENTS.md", repo_dir / "CLAUDE.md"]:
        if check_file.exists() and "Domain Boundaries & Zero-Infringement" in check_file.read_text():
            has_policy = True
            break
            
    if not has_policy:
        violations.append({
            "repo": repo_name,
            "type": "MISSING_POLICY",
            "file": "AGENTS.md",
            "message": "Repository is missing Domain Boundaries & Zero-Infringement policy."
        })
        
    # 2. Scan code files for foreign domain infringement
    for ext in ["*.py", "*.sql", "*.js", "*.ts"]:
        for fpath in repo_dir.rglob(ext):
            # Skip virtual environments, node_modules, git, and this linter script
            if fpath.name == "lint_domain_boundaries.py" or any(p in fpath.parts for p in [".git", "venv", ".venv", "node_modules", "archive", "dist", "build"]):
                continue
            
            try:
                content = fpath.read_text(errors="ignore")
            except Exception:
                continue
                
            for rule in INFRINGEMENT_PATTERNS:
                if repo_name not in rule["allowed_repos"]:
                    match = re.search(rule["regex"], content, re.IGNORECASE)
                    if match:
                        violations.append({
                            "repo": repo_name,
                            "type": "DOMAIN_INFRINGEMENT",
                            "file": str(fpath.relative_to(repo_dir)),
                            "match": match.group(0),
                            "message": f"[{rule['domain']}] {rule['message']}"
                        })
                        
    return violations

def main():
    parser = argparse.ArgumentParser(description="Fleet Domain Boundary Linter")
    parser.add_argument("--repo", help="Path to single repo to check")
    parser.add_argument("--all", action="store_true", help="Check all repositories in /Users/gslee/Projects")
    parser.add_argument("--strict", action="store_true", help="Exit with non-zero code on violations")
    args = parser.parse_args()
    
    targets = []
    if args.repo:
        targets.append(Path(args.repo))
    elif args.all:
        base = Path("/Users/gslee/Projects")
        targets = [p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name != "archive"]
    else:
        # Default to current directory
        targets.append(Path.cwd())
        
    all_violations = []
    for t in sorted(targets):
        v = check_repo_boundaries(t)
        all_violations.extend(v)
        
    if not all_violations:
        print("\n✅ All repositories passed Domain Boundary and Anti-Infringement checks!")
        sys.exit(0)
        
    print(f"\n[!] Found {len(all_violations)} boundary issues across inspected repositories:\n")
    for v in all_violations:
        print(f"• [{v['repo']}] {v['type']} in `{v['file']}`: {v['message']}")
        if "match" in v:
            print(f"  Matched: '{v['match']}'")
            
    if args.strict:
        sys.exit(1)

if __name__ == "__main__":
    main()
