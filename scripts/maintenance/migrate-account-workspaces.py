"""Read-only preview by default. Use the repository's account-layout migration code."""

import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "api" / "src"))
    from viral_dna_api.accounts.migrate_workspaces import main as migrate

    return migrate()


if __name__ == "__main__":
    raise SystemExit(main())
