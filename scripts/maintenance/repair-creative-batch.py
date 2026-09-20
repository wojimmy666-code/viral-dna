"""Recover a saved, ellipsis-rejected ideas batch; preview unless --apply."""

import sys
from pathlib import Path


def main():
    sys.path.insert(
        0, str(Path(__file__).resolve().parents[2] / "services" / "api" / "src")
    )
    from viral_dna_api.viral_insights.creative_recovery import main as repair

    return repair()


if __name__ == "__main__":
    raise SystemExit(main())
