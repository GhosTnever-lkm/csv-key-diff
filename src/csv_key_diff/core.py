"""Core CSV loading, keyed comparison, and stable report serialization."""
from __future__ import annotations

import csv
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CsvDiffError(ValueError):
    """An input file cannot be compared safely or unambiguously."""


@dataclass(frozen=True)
class CsvData:
    columns: tuple[str, ...]
    rows: dict[str, dict[str, str]]


@dataclass(frozen=True)
class DiffResult:
    key_column: str
    columns: tuple[str, ...]
    added: tuple[dict[str, str], ...]
    removed: tuple[dict[str, str], ...]
    changed: tuple[dict[str, Any], ...]
    unchanged_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "key_column": self.key_column,
            "columns": list(self.columns),
            "summary": {
                "added": len(self.added),
                "removed": len(self.removed),
                "changed": len(self.changed),
                "unchanged": self.unchanged_count,
            },
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": list(self.changed),
        }


def read_csv(path: str | Path, key_column: str, max_bytes: int = 10 * 1024 * 1024) -> CsvData:
    """Read one bounded UTF-8 CSV, rejecting ambiguous headers, rows, and keys."""
    source = Path(path)
    try:
        size = source.stat().st_size
        if size > max_bytes:
            raise CsvDiffError(f"{source.name}: file exceeds the {max_bytes}-byte limit")
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = reader.fieldnames
            if not fields:
                raise CsvDiffError(f"{source.name}: CSV has no header row")
            if any(name is None or not name.strip() for name in fields):
                raise CsvDiffError(f"{source.name}: column names must not be empty")
            if len(fields) != len(set(fields)):
                raise CsvDiffError(f"{source.name}: duplicate column names are not supported")
            if key_column not in fields:
                raise CsvDiffError(f"{source.name}: key column {key_column!r} was not found")
            rows: dict[str, dict[str, str]] = {}
            for line_number, row in enumerate(reader, start=2):
                if None in row or any(value is None for value in row.values()):
                    raise CsvDiffError(f"{source.name}: row {line_number} has a different number of fields than the header")
                key = row[key_column]
                if not key.strip():
                    raise CsvDiffError(f"{source.name}: row {line_number} has an empty key in {key_column!r}")
                if key in rows:
                    raise CsvDiffError(f"{source.name}: duplicate key at row {line_number} in {key_column!r}")
                rows[key] = dict(row)
            return CsvData(tuple(fields), rows)
    except CsvDiffError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        # Do not include row data in diagnostics; input values can be sensitive.
        raise CsvDiffError(f"{source.name}: could not read a valid UTF-8 CSV ({type(exc).__name__})") from None


def compare_csv(before: CsvData, after: CsvData, key_column: str) -> DiffResult:
    """Compare two files by key; header order may differ, but schema must match."""
    if set(before.columns) != set(after.columns):
        left_only = sorted(set(before.columns) - set(after.columns))
        right_only = sorted(set(after.columns) - set(before.columns))
        details = []
        if left_only:
            details.append("removed columns: " + ", ".join(left_only))
        if right_only:
            details.append("added columns: " + ", ".join(right_only))
        raise CsvDiffError("CSV schemas differ (" + "; ".join(details) + ")")
    if key_column not in before.columns:
        raise CsvDiffError(f"key column {key_column!r} was not found in both files")

    shared_keys = before.rows.keys() & after.rows.keys()
    added = tuple(after.rows[key] for key in sorted(after.rows.keys() - before.rows.keys()))
    removed = tuple(before.rows[key] for key in sorted(before.rows.keys() - after.rows.keys()))
    changed: list[dict[str, Any]] = []
    unchanged = 0
    columns = tuple(sorted(before.columns))
    for key in sorted(shared_keys):
        changes = [
            {"field": field, "before": before.rows[key][field], "after": after.rows[key][field]}
            for field in columns
            if before.rows[key][field] != after.rows[key][field]
        ]
        if changes:
            changed.append({"key": key, "fields": changes})
        else:
            unchanged += 1
    return DiffResult(key_column, columns, added, removed, tuple(changed), unchanged)


def compare_files(before_path: str | Path, after_path: str | Path, key_column: str,
                  max_bytes: int = 10 * 1024 * 1024) -> DiffResult:
    before = read_csv(before_path, key_column, max_bytes)
    after = read_csv(after_path, key_column, max_bytes)
    return compare_csv(before, after, key_column)


def render_json(result: DiffResult) -> str:
    return json.dumps(result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _cell(value: str) -> str:
    """Escape untrusted values so Markdown treats them as plain table text."""
    escaped = html.escape(value.replace("\\", "\\\\"), quote=False)
    for character in "|[]()*_`~":
        escaped = escaped.replace(character, "\\" + character)
    return escaped.replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")


def _code(value: str) -> str:
    """Wrap arbitrary input in an inline code span without delimiter collisions."""
    longest = max((len(run) for run in re.findall(r"`+", value)), default=0)
    delimiter = "`" * (longest + 1)
    padding = " " if value.startswith((" ", "`")) or value.endswith((" ", "`")) else ""
    return f"{delimiter}{padding}{value}{padding}{delimiter}"


def render_markdown(result: DiffResult) -> str:
    summary = result.as_dict()["summary"]
    lines = [
        "# CSV Key Diff report",
        "",
        f"Key column: {_code(result.key_column)}",
        "",
        f"Added: **{summary['added']}** · Removed: **{summary['removed']}** · Changed: **{summary['changed']}** · Unchanged: **{summary['unchanged']}**",
    ]
    if result.added:
        lines.extend(["", "## Added rows", "", f"Keys: {', '.join(_code(row[result.key_column]) for row in result.added)}"])
    if result.removed:
        lines.extend(["", "## Removed rows", "", f"Keys: {', '.join(_code(row[result.key_column]) for row in result.removed)}"])
    if result.changed:
        lines.extend(["", "## Changed fields", "", "| Key | Field | Before | After |", "| --- | --- | --- | --- |"])
        for entry in result.changed:
            for change in entry["fields"]:
                cells = (entry["key"], change["field"], change["before"], change["after"])
                lines.append("| " + " | ".join(_cell(value) for value in cells) + " |")
    return "\n".join(lines) + "\n"
