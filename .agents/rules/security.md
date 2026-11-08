# devsecops-allowlist
# Fleet Security Policy: Zero Plaintext Secret Exposure & JIT Governance

You MUST follow these strict security rules at all times across all projects:

## 1. Zero Plaintext Secret "Blurt" Rule
- **NEVER print, blurt, write to markdown, log, or display raw passwords, auth tokens, database credentials, or private keys in chat, logs, or commit diffs.**
- Always mask or redact credentials in output: e.g. `postgres://user:***@host:port/db` or `[REDACTED_TOKEN]`.
- In application code, reference secrets exclusively via environment variables (`os.getenv(...)`) or parameter files (`.env`).
- Never commit `.env` files or credentials to git version control.

## 2. Just-In-Time (JIT) Secret Broker MCP Usage
- When an agent requires database or API credentials to perform an automated task:
  1. **Do NOT** ask the user to type passwords in chat.
  2. Call the MCP tool: `request_secret_access(resource_id, requester, reason, duration_minutes)`.
  3. The superuser will receive an instant approval notification.
  4. Once approved, call `get_secret(ticket_id)` to receive an ephemeral, time-limited leased credential in-memory.
  5. Never persist the returned secret value to disk or commit history.

## 3. Zero Hardcoded LAN IP Policy
- Never hardcode intranet/LAN IP addresses (`192.168.10.*`).
- Use Tailscale MagicDNS (`*.ts.net`) or canonical service endpoints (`rv-cloud.local`).

## 4. Exclusive Infrastructure & Network Authority (Infra-Agent Sole Ownership)
- **ONLY Infra-Control-Plane (`Infra-Agent` in `fleet-rationalization`) is permitted to configure or alter networking, firewalls, Tailscale (ACLs/Serve/Funnel), SSH access, port allocations, routing, or device-level infrastructure across fleet nodes (`pi-3`, `pi-4`, `NAS`, `oppenheimer`, `Mac`).**
- **Mandatory User Permission Gate**: Even `Infra-Agent` CANNOT execute network topology or infrastructure modifications without explicit, prior user approval.
- **Strict Prohibition for Application / Domain Coding Agents**:
  - Application agents (`Work-RAG`, `VisiRAG`, `AI-CRM`, `Contact-Mgmt`, `Job-Applications`, `GeBiz`, etc.) are **STRICTLY PROHIBITED** from:
    1. Altering network routing, DNS, `/etc/hosts`, or firewall/iptables rules.
    2. Modifying SSH daemon configurations, keys, or creating unauthorized tunnels (`ssh -R` / `-L` / `-D`).
    3. Bypassing device sandboxing or network segmentation (especially on isolated worker nodes like `oppenheimer` tagged `worker-isolated`, or direct access to NAS internal databases).
    4. Installing, modifying, or deleting systemd, launchd, or Termux background daemon services on any fleet device.
    5. Exposing unauthenticated ports or binding internal services to `0.0.0.0`.

## 5. Network & Infrastructure Change Delegation Protocol
- When an application agent encounters a network connection issue, missing port, or requires infrastructure changes:
  1. **DO NOT** attempt local workarounds, raw IP overrides, proxy tunnels, or node configuration changes.
  2. **Delegate formally** to `fleet-rationalization` via cross-agent task:
     ```bash
     python3 /Users/gslee/Projects/fleet-rationalization/scripts/cross_agent_delegate.py \
       --from-repo "<current_repo>" \
       --to-repo "fleet-rationalization" \
       --type "infra_request" \
       --title "<request title>" \
       --description "<detailed network or infrastructure requirement>"
     ```
  3. Mark state in `HANDOVER.md` as `BLOCKED_ON_DELEGATION: [TICKET_ID]` and block execution until Infra-Agent (with explicit user approval) provisions the change.
