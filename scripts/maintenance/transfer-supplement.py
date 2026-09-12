"""Incremental category/Skill display/model-key transfer; import is preview-only by default."""

import sys
from pathlib import Path


def main():
    sys.path.insert(
        0, str(Path(__file__).resolve().parents[2] / "services" / "api" / "src")
    )
    from viral_dna_api.accounts.supplement_transfer import main as transfer

    return transfer()


if __name__ == "__main__":
    raise SystemExit(main())
