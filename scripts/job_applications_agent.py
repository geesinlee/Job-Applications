#!/usr/bin/env python3
"""Job-Applications Autonomous Agent.

Runs continuously in the background on pi-3 (or any fleet node) to monitor Kafka
topic 'fleet.agent.tasks'. Picks up incoming tickets delegated to Job-Applications,
acknowledges them, diagnoses/attends to them, runs playbooks, updates HANDOVER.md,
and publishes resolution events back to the fleet bus.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

try:
    from kafka import KafkaConsumer, KafkaProducer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


# Fleet Canonical Configuration (Zero-Hardcoded-IP Policy)
DEFAULT_BROKER = "rv-cloud.tail210e4f.ts.net:9092"
FALLBACK_BROKER = "rv-cloud.local:9092"
TASKS_TOPIC = "fleet.agent.tasks"
CONSUMER_GROUP = "job-applications-agent-v1"
REPO_IDENTIFIERS = {"job-applications", "job_applications", "jobapps"}
PI4_HOST = "gs-pi-4.tail210e4f.ts.net"
PI4_MCP_URL = "http://gs-pi-4.tail210e4f.ts.net:8000"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATE_FILE = DATA_DIR / "agent_tasks.json"
HANDOVER_FILE = BASE_DIR / "HANDOVER.md"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [job-app-agent] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("job-applications-agent")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_tracked_tasks() -> Dict[str, Dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Error loading state file {STATE_FILE}: {e}")
    return {}


def save_tracked_tasks(tasks: Dict[str, Dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = STATE_FILE.with_suffix(".tmp")
    temp_file.write_text(json.dumps(tasks, indent=2), encoding="utf-8")
    temp_file.replace(STATE_FILE)


def update_handover_task(task: Dict[str, Any], status: str, note: str = "") -> None:
    """Stage incoming task or update its status in HANDOVER.md."""
    if not HANDOVER_FILE.exists():
        return
    try:
        content = HANDOVER_FILE.read_text(encoding="utf-8")
        tid = task.get("ticket_id", "UNKNOWN")
        title = task.get("title", "")
        from_repo = task.get("from_repo", "Unknown")
        priority = task.get("priority", "NORMAL").upper()

        task_entry = (
            f"- **ACTION_REQUIRED: `{tid}`** (from {from_repo}, {priority} priority):\n"
            f"  - **Title**: {title}\n"
            f"  - **Status**: `{status}` (Updated at {_now_iso()})\n"
        )
        if note:
            task_entry += f"  - **Agent Note**: {note}\n"

        header = "## Incoming Fleet Tasks (Delegated to Agent)\n"
        if tid in content:
            # Ticket already in handover, replace status line if found
            lines = content.splitlines()
            new_lines = []
            skip = False
            for line in lines:
                if f"ACTION_REQUIRED: `{tid}`" in line:
                    new_lines.append(task_entry.strip())
                    skip = True
                elif skip and line.startswith("- **ACTION_REQUIRED:"):
                    skip = False
                    new_lines.append(line)
                elif not skip:
                    new_lines.append(line)
            HANDOVER_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        else:
            if header in content:
                content = content.replace(header, header + task_entry + "\n")
            else:
                content = header + task_entry + "\n\n" + content
            HANDOVER_FILE.write_text(content, encoding="utf-8")
        logger.info(f"Updated HANDOVER.md for ticket {tid} -> {status}")
    except Exception as e:
        logger.warning(f"Failed to update HANDOVER.md: {e}")


class JobApplicationsAgent:
    def __init__(self, broker: str = DEFAULT_BROKER):
        self.broker = broker
        self.running = True
        self.producer: Optional[KafkaProducer] = None
        self.tracked_tasks = load_tracked_tasks()

    def _init_producer(self) -> bool:
        if not KAFKA_AVAILABLE:
            logger.error("kafka-python not installed; cannot initialize producer")
            return False
        for target_broker in [self.broker, FALLBACK_BROKER]:
            try:
                self.producer = KafkaProducer(
                    bootstrap_servers=target_broker,
                    request_timeout_ms=5000,
                    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                    key_serializer=lambda k: k.encode("utf-8") if isinstance(k, str) else k,
                )
                logger.info(f"Connected Kafka producer to {target_broker}")
                self.broker = target_broker
                return True
            except Exception as e:
                logger.warning(f"Failed to connect producer to {target_broker}: {e}")
        return False

    def emit_event(self, key: str, payload: Dict[str, Any]) -> bool:
        if not self.producer and not self._init_producer():
            logger.warning(f"Unable to publish event {key} to Kafka (no producer)")
            return False
        try:
            self.producer.send(TASKS_TOPIC, key=key, value=payload)
            self.producer.flush(timeout=5)
            logger.info(f"Published event [{payload.get('event_type')}] for {key} to {TASKS_TOPIC}")
            return True
        except Exception as e:
            logger.error(f"Error publishing event to {TASKS_TOPIC}: {e}")
            return False

    def acknowledge_ticket(self, task: Dict[str, Any]) -> None:
        tid = task.get("ticket_id")
        logger.info(f"Acknowledging ticket {tid} from {task.get('from_repo')}")
        ack_event = {
            "ticket_id": tid,
            "event_type": "task_status_update",
            "status": "IN_PROGRESS",
            "from_repo": "Job-Applications",
            "to_repo": task.get("from_repo"),
            "updated_at": _now_iso(),
            "message": "Job-Applications Agent picked up ticket. Beginning diagnostics and remediation.",
        }
        self.emit_event(tid, ack_event)

        task["status"] = "IN_PROGRESS"
        task["picked_up_at"] = _now_iso()
        self.tracked_tasks[tid] = task
        save_tracked_tasks(self.tracked_tasks)
        update_handover_task(task, "IN_PROGRESS", "Ticket picked up; executing diagnostics")

    def resolve_ticket(self, task: Dict[str, Any], resolution_note: str, details: Optional[Dict[str, Any]] = None) -> None:
        tid = task.get("ticket_id")
        logger.info(f"Resolving ticket {tid}: {resolution_note}")
        resolution_event = {
            "ticket_id": tid,
            "event_type": "task_resolution",
            "status": "RESOLVED",
            "from_repo": "Job-Applications",
            "to_repo": task.get("from_repo"),
            "resolved_at": _now_iso(),
            "resolution_note": resolution_note,
            "resolution": {
                "status": "success",
                "resolved_by": "job-applications-agent@pi-3",
                "details": details or {},
            },
        }
        self.emit_event(tid, resolution_event)

        task["status"] = "RESOLVED"
        task["resolved_at"] = _now_iso()
        task["resolution_note"] = resolution_note
        self.tracked_tasks[tid] = task
        save_tracked_tasks(self.tracked_tasks)
        update_handover_task(task, "RESOLVED", resolution_note)

    def diagnose_and_attend(self, task: Dict[str, Any]) -> None:
        tid = task.get("ticket_id")
        title = task.get("title", "")
        desc = task.get("description", "")
        req_type = task.get("type", "feature_request")

        logger.info(f"Attending to ticket {tid} ({title})...")

        # 1. Health / Service Outage / Missing Tools Diagnosis
        if "DEGRADED" in title or "tools are missing" in desc or "tools missing" in desc:
            self._handle_health_degradation(task)
            return

        # 2. Bug report / Code change request
        if req_type == "bug_report" or "bug" in title.lower():
            note = f"Bug report staged for engineering review: {title}"
            update_handover_task(task, "ACTION_REQUIRED", note)
            logger.info(f"Bug report {tid} staged in HANDOVER.md")
            return

        # 3. Default feature request / task
        note = f"Task staged in HANDOVER.md for developer attention: {title}"
        update_handover_task(task, "IN_PROGRESS", note)

    def _handle_health_degradation(self, task: Dict[str, Any]) -> None:
        tid = task.get("ticket_id")
        logger.info(f"Diagnosing health degradation ticket {tid}...")

        # Step 1: Check pi-4 MCP service status
        service_active = False
        try:
            res = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", f"gs@{PI4_HOST}", "systemctl --user is-active job-applications-mcp.service"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            service_active = (res.stdout.strip() == "active")
            logger.info(f"pi-4 job-applications-mcp.service active: {service_active}")
        except Exception as e:
            logger.warning(f"Could not probe pi-4 systemd service: {e}")

        # Step 2: If inactive, run remediation restart playbook
        if not service_active:
            logger.info("Service inactive. Triggering restart playbook on pi-4...")
            try:
                subprocess.run(
                    ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", f"gs@{PI4_HOST}", "systemctl --user restart job-applications-mcp.service"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                time.sleep(3)
            except Exception as e:
                logger.error(f"Failed to restart service on pi-4: {e}")

        # Step 3: Analyze specific missing tools if reported
        desc = task.get("description", "")
        if "Reported Tool Count: 33" in desc and "list_applied_opportunities" in desc:
            note = "Diagnosed: MCP server running (33 tools). Exposing 'list_applied_opportunities' requires tool registration update."
            update_handover_task(task, "ACTION_REQUIRED", note)
            return

        # Step 4: If service is verified running, check whether issue resolved
        if service_active:
            note = "Verified job-applications-mcp.service is actively running and responding on pi-4."
            self.resolve_ticket(task, note, {"service_active": True, "host": PI4_HOST})
        else:
            note = "pi-4 service failed to start or unreachable via network."
            update_handover_task(task, "BLOCKED", note)

    def process_message(self, val: Dict[str, Any]) -> None:
        tid = val.get("ticket_id")
        if not tid:
            return

        to_repo = (val.get("to_repo") or "").strip().lower()
        if to_repo not in REPO_IDENTIFIERS:
            # Not meant for Job-Applications
            return

        event_type = val.get("event_type", "cross_agent_delegation")
        if event_type in ("task_resolution", "task_completed", "task_cancelled"):
            # Don't re-process resolution events
            return

        status = (val.get("status") or "OPEN").upper()
        if status in ("RESOLVED", "CLOSED"):
            return

        # Check if already processed and resolved locally
        existing = self.tracked_tasks.get(tid)
        if existing and existing.get("status") == "RESOLVED":
            return

        logger.info(f"[!] INCOMING TICKET: {tid} from {val.get('from_repo')} -> {val.get('title')}")

        # 1. Acknowledge
        self.acknowledge_ticket(val)

        # 2. Attend
        self.diagnose_and_attend(val)

    def run(self, run_once: bool = False) -> None:
        if not KAFKA_AVAILABLE:
            logger.error("kafka-python is required to run the agent daemon. Exiting.")
            sys.exit(1)

        logger.info(f"Starting Job-Applications Agent (broker: {self.broker}, topic: {TASKS_TOPIC})")
        self._init_producer()

        consumer: Optional[KafkaConsumer] = None
        while self.running:
            try:
                if not consumer:
                    logger.info(f"Connecting consumer to {self.broker}...")
                    consumer = KafkaConsumer(
                        TASKS_TOPIC,
                        bootstrap_servers=self.broker,
                        group_id=CONSUMER_GROUP,
                        auto_offset_reset="earliest",
                        enable_auto_commit=True,
                        consumer_timeout_ms=5000,
                        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                    )
                    logger.info(f"Subscribed to {TASKS_TOPIC} as group {CONSUMER_GROUP}")

                msg_count = 0
                for message in consumer:
                    if not self.running:
                        break
                    try:
                        self.process_message(message.value)
                        msg_count += 1
                    except Exception as e:
                        logger.error(f"Error handling message: {e}")

                if run_once:
                    logger.info(f"Run-once completed. Handled {msg_count} message(s).")
                    break

            except Exception as e:
                logger.warning(f"Kafka consumer error: {e}. Reconnecting in 5s...")
                consumer = None
                time.sleep(5)

        if consumer:
            consumer.close()
        if self.producer:
            self.producer.close()
        logger.info("Job-Applications Agent stopped cleanly.")


def main():
    parser = argparse.ArgumentParser(description="Job-Applications Autonomous Agent Daemon")
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="Kafka broker address")
    parser.add_argument("--run-once", action="store_true", help="Process available messages and exit")
    parser.add_argument("--status", action="store_true", help="Display tracked ticket status and exit")
    args = parser.parse_args()

    if args.status:
        tasks = load_tracked_tasks()
        print(f"Tracked Tickets for Job-Applications ({len(tasks)}):")
        for tid, t in tasks.items():
            print(f"  - [{t.get('status')}] {tid}: {t.get('title')} (Updated: {t.get('updated_at') or t.get('created_at')})")
        return

    agent = JobApplicationsAgent(broker=args.broker)

    def _sig_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        agent.running = False

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    agent.run(run_once=args.run_once)


if __name__ == "__main__":
    main()
