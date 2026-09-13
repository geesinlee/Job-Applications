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
