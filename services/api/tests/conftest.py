from __future__ import annotations

import os

# Tests must never create or reuse the developer's durable SQLite database.
os.environ["VIRAL_DNA_STORE"] = "memory"
os.environ["VIRAL_DNA_SIMULATION_DELAY"] = "0.01"
