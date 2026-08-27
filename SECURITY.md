# Security and tenant-data policy

## Keep tenant data out of source control

Job applications, CVs, generated documents, OAuth material, local client
configuration, and runtime state are deployment data. Keep them in the ignored
`data/` tree or in paths configured through environment variables. Do not commit
`.env`, company folders, bearer tokens, SMTP credentials, database URLs, or OAuth
client secrets.

Top-level directories are ignored by default so legacy company folders remain
local. Repository source directories are explicitly allowlisted in `.gitignore`;
add any new source directory to that allowlist before committing it.

Use the checked-in example configuration files as templates:

- `.env.example`
- `claude_config.json.example`
- `.agents/mcp_config.json.example`

## Reporting a vulnerability

Report security issues privately to the repository owner. Do not include live
credentials, personal documents, or production records in a public issue.

## Credential exposure

If a credential is committed, treat it as compromised: revoke or rotate it,
remove it from the current tree, and purge it from Git history before publishing
the repository. Removing a file in a later commit does not remove earlier copies
from Git history.
