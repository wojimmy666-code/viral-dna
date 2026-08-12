from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from viral_dna_api.models import AnalysisReport

from .contracts import GoldenAnalysisExpectation
from .golden import evaluate_golden_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="对 ViralDNA 分析报告运行零费用黄金样本回归",
    )
    parser.add_argument("--expectation", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        expectation = GoldenAnalysisExpectation.model_validate_json(
            args.expectation.read_text(encoding="utf-8")
        )
        report = AnalysisReport.model_validate_json(args.report.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as error:
        print(f"无法读取黄金样本或分析报告：{error}", file=sys.stderr)
        return 2

    result = evaluate_golden_report(report, expectation)
    serialized = result.model_dump_json(indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{serialized}\n", encoding="utf-8")
    print(
        f"{'PASS' if result.passed else 'FAIL'} {result.sample_id} "
        f"score={result.score} errors={result.error_count} warnings={result.warning_count}"
    )
    return 0 if result.passed else 1


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
