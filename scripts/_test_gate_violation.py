"""Throwaway file to trip the harness ComplianceSentinel gate on CI.
Not real code — deliberate violations for gate verification only.
"""

# VIOLATION 1: hardcoded LAN IP (fleet Zero-LAN-IP policy)
DATABASE_HOST = "192.168.10.5"
DATABASE_PORT = 5432

# VIOLATION 2: plaintext secret (Zero Plaintext Secret rule)
API_KEY = "sk-test-live-1234567890abcdef"

# VIOLATION 3: plaintext password
DB_PASSWORD = "hunter2-supersecret"