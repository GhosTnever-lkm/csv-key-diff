"""Command-line entry point for csv-key-diff."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from . import __version__
from .core import CsvDiffError, compare_files, render_json, render_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="csv-key-diff",
        description="Compare two CSV exports by a unique key. Files are processed locally.",
        epilog="Exit codes: 0 = valid report (or no changes with --fail-on-changes); 1 = changes found with --fail-on-changes; 2 = invalid input or I/O error.",
    )
    parser.add_argument("before", help="baseline CSV file")
    parser.add_argument("after", help="new CSV file")
    parser.add_argument("--key", required=True, help="column whose values uniquely identify rows")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown", help="report format (default: markdown)")
    parser.add_argument("--output", type=Path, help="write report to a file instead of stdout")
    parser.add_argument("--max-bytes", type=int, default=10 * 1024 * 1024, help="maximum size per input file (default: 10 MiB)")
    parser.add_argument("--fail-on-changes", action="store_true", help="exit 1 when the report contains added, removed, or changed rows")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _atomic_write(destination: Path, content: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=destination.parent,
                                         prefix=f".{destination.name}.", delete=False) as handle:
            temp_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_bytes <= 0:
        parser.error("--max-bytes must be a positive integer")
    if args.output:
        output_path = args.output.expanduser().resolve()
        if output_path in (Path(args.before).expanduser().resolve(), Path(args.after).expanduser().resolve()):
            parser.error("--output must not overwrite either input file")
    try:
        result = compare_files(args.before, args.after, args.key, args.max_bytes)
        report = render_json(result) if args.format == "json" else render_markdown(result)
        if args.output:
            _atomic_write(args.output, report)
        else:
            sys.stdout.write(report)
        counts = result.as_dict()["summary"]
        has_changes = any(counts[name] for name in ("added", "removed", "changed"))
        return 1 if args.fail_on_changes and has_changes else 0
    except CsvDiffError as exc:
        print(f"csv-key-diff: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"csv-key-diff: output could not be written ({type(exc).__name__})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
