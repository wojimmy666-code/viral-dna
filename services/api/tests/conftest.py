from __future__ import annotations

import os

# Tests must never create or reuse the developer's durable SQLite database.
os.environ["VIRAL_DNA_STORE"] = "memory"
# Legacy business tests deliberately use the explicit loopback-only development mode.
# Account/security tests override this with password authentication and isolated databases.
os.environ["VIRAL_DNA_AUTH_MODE"] = "local_bootstrap"
os.environ["VIRAL_DNA_SIMULATION_DELAY"] = "0.01"
os.environ["VIRAL_DNA_VLM_PROVIDER"] = "disabled"
