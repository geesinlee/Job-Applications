#!/usr/bin/env python3
"""Job-Applications Autonomous Agent Runner.

Centralized fleet worker shim delegating to fleet-rationalization's
standardized RepoTaskWorker daemon for Job-Applications.
"""

import sys
import os
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent

POSSIBLE_FLEET_PATHS = [
    REPO_DIR.parent / "fleet-rationalization" / "scripts",
    Path("/Users/gslee/Projects/fleet-rationalization/scripts"),
    Path("/home/gs/Projects/fleet-rationalization/scripts"),
]

worker_script = None
for p in POSSIBLE_FLEET_PATHS:
    cand = p / "repo_task_worker.py"
    if cand.exists():
        worker_script = cand
        break

if not worker_script:
    sys.stderr.write("[-] Error: Could not locate fleet-rationalization/scripts/repo_task_worker.py\n")
    sys.exit(1)

cmd = [sys.executable, str(worker_script), "--repo", "Job-Applications", "--repo-dir", str(REPO_DIR)]
cmd.extend(sys.argv[1:])

os.execv(sys.executable, cmd)
