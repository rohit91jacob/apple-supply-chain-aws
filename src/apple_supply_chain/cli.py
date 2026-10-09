"""``asc`` command line.

Exit codes: 0 ok, 1 failure, 2 usage/config error, 3 data-quality failure,
4 verification mismatch.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from apple_supply_chain.config import ConfigError, Settings
from apple_supply_chain.logs import configure_logging, get_logger

log = get_logger("apple_supply_chain.cli")

EXIT_OK, EXIT_FAILURE, EXIT_USAGE, EXIT_DQ, EXIT_MISMATCH = 0, 1, 2, 3, 4
SOURCES = ("sec_edgar", "apple_supplier_list", "un_comtrade", "us_census")


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _print_checks(result: dict) -> None:
    for c in result["checks"]:
        status = "PASS" if c["passed"] else "FAIL"
        print(f"{status}  {c['severity']:<5}  [{c['layer']}] {c['name']}  ({c['violations']})")
    print(f"-> {result['errors']} error(s), {result['warnings']} warning(s)")


# ------------------------------------------------------------------ commands
def cmd_extract(args, settings: Settings) -> int:
    from apple_supply_chain.extract import run_extractor  # noqa: PLC0415

    for name in args.source or SOURCES:
        _print(run_extractor(name, settings))
    return EXIT_OK


def cmd_silver(args, settings: Settings) -> int:
    from apple_supply_chain.transform.silver import build_silver  # noqa: PLC0415

    _print(build_silver(settings, run_id=args.run_id))
    return EXIT_OK


def cmd_dq(args, settings: Settings) -> int:
    from apple_supply_chain.quality import run_gold_checks, run_silver_checks  # noqa: PLC0415

    failed = False
    for layer in ["silver", "gold"] if args.layer == "all" else [args.layer]:
        result = run_silver_checks(settings) if layer == "silver" else run_gold_checks(settings)
        _print_checks(result)
        failed |= not result["passed"]
    return EXIT_DQ if failed else EXIT_OK


def cmd_marts(args, settings: Settings) -> int:
    from apple_supply_chain.warehouse import build_marts  # noqa: PLC0415

    _print(build_marts(settings, run_id=args.run_id))
    return EXIT_OK


def cmd_graph(args, settings: Settings) -> int:
    from apple_supply_chain.graph.build import build_graph_outputs  # noqa: PLC0415

    _print(build_graph_outputs(settings, run_id=args.run_id))
    return EXIT_OK


def cmd_pipeline(args, settings: Settings) -> int:
    from apple_supply_chain.pipeline import run_pipeline  # noqa: PLC0415

    result = run_pipeline(settings, run_id=args.run_id or None, skip_extract=args.skip_extract)
    _print(result)
    if result["status"] == "SUCCEEDED":
        return EXIT_OK
    return EXIT_DQ if result.get("error") == "DataQualityFailed" else EXIT_FAILURE


def cmd_report(args, settings: Settings) -> int:
    from apple_supply_chain.report.site import build_site  # noqa: PLC0415

    _print(build_site(settings, Path(args.out)))
    return EXIT_OK


def cmd_verify(args, settings: Settings) -> int:
    from apple_supply_chain.verify import run_verification  # noqa: PLC0415

    result = run_verification(settings, Path(args.out))
    print(f"{result['matched']} / {result['compared']} figures match the published statements")
    for m in result["mismatches"]:
        print(
            f"  MISMATCH {m['fiscal_year']} {m['line_item']}: pipeline {m['pipeline']} vs published {m['published']}"
        )
    return EXIT_MISMATCH if result["mismatches"] else EXIT_OK


def cmd_fixtures(args, settings: Settings) -> int:
    from apple_supply_chain.fixtures import build_fixture_tree  # noqa: PLC0415

    _print(build_fixture_tree(Path(args.out), Path(args.committed)))
    return EXIT_OK


def cmd_glue_sync(args, settings: Settings) -> int:
    from apple_supply_chain.lakehouse.glue_sync import sync_to_glue  # noqa: PLC0415

    _print(sync_to_glue(settings, database_prefix=args.database_prefix))
    return EXIT_OK


def cmd_render_asl(args, settings: Settings) -> int:
    from apple_supply_chain.orchestration.render import render_definition  # noqa: PLC0415

    print(render_definition(args.account_id, args.region, args.prefix))
    return EXIT_OK


def cmd_sql(args, settings: Settings) -> int:
    from apple_supply_chain.warehouse import connect  # noqa: PLC0415

    con = connect(settings)
    try:
        print(con.sql(args.query))
    finally:
        con.close()
    return EXIT_OK


# ------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="asc", description="Apple supply chain analytics pipeline")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("extract", help="download sources into the raw bucket")
    s.add_argument("--source", action="append", choices=SOURCES, help="repeatable; default: all")
    s.set_defaults(func=cmd_extract)

    for name, func, help_text in (
        ("silver", cmd_silver, "raw -> silver Iceberg tables"),
        ("marts", cmd_marts, "silver -> DuckDB -> dbt build -> gold Iceberg"),
        ("graph", cmd_graph, "supplier network graph, HHI and disruption scenarios"),
    ):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("--run-id", default="manual")
        s.set_defaults(func=func)

    s = sub.add_parser("dq", help="run data-quality checks (exit 3 on error-level failures)")
    s.add_argument("--layer", choices=["silver", "gold", "all"], default="all")
    s.set_defaults(func=cmd_dq)

    s = sub.add_parser("pipeline", help="run the Step Functions definition locally, end to end")
    s.add_argument("--run-id", default="")
    s.add_argument("--skip-extract", action="store_true", help="rebuild from the existing raw zone")
    s.set_defaults(func=cmd_pipeline)

    s = sub.add_parser("report", help="write the static results site")
    s.add_argument("--out", default="site")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("verify", help="reconcile outputs with Apple's published statements")
    s.add_argument("--out", default="docs/verification_results.json")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("fixtures", help="assemble offline fixtures (real SEC + SYNTHETIC others)")
    s.add_argument("--out", required=True)
    s.add_argument("--committed", default="tests/fixtures")
    s.set_defaults(func=cmd_fixtures)

    s = sub.add_parser(
        "glue-sync", help="register Iceberg tables in an AWS Glue catalog (moto/LocalStack/AWS)"
    )
    s.add_argument("--database-prefix", default="asc_")
    s.set_defaults(func=cmd_glue_sync)

    s = sub.add_parser("render-asl", help="print the state machine with concrete Lambda ARNs")
    s.add_argument("--account-id", default="000000000000")
    s.add_argument("--region", default="eu-west-1")
    s.add_argument("--prefix", default="asc-dev")
    s.set_defaults(func=cmd_render_asl)

    s = sub.add_parser("sql", help="run a SQL query against the DuckDB warehouse")
    s.add_argument("query")
    s.set_defaults(func=cmd_sql)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    configure_logging(settings.log_format)
    try:
        return args.func(args, settings)
    except Exception:
        log.exception("asc %s failed", args.command)
        return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
