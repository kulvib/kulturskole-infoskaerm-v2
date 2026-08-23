"""Step 53B schema delta: retire plaintext local System secret storage."""

SYSTEM_AUTHORITY_RETIRED_CLIENT_COLUMNS = frozenset({"local_management_secret"})
