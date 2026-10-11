from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from csv_key_diff.core import CsvDiffError, compare_files, read_csv, render_json, render_markdown


class CsvDiffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.before = self.root / "before.csv"
        self.after = self.root / "after.csv"

    def tearDown(self):
        self.temp.cleanup()

    def write_pair(self, before: str, after: str):
        # newline="" keeps embedded LF in quoted fields intact on Windows,
        # where text mode would otherwise translate them to CRLF.
        with open(self.before, "w", encoding="utf-8", newline="") as handle:
            handle.write(before)
        with open(self.after, "w", encoding="utf-8", newline="") as handle:
            handle.write(after)

    def test_reports_added_removed_changed_and_unchanged_rows(self):
        self.write_pair("id,name,qty\n1,alpha,2\n2,beta,1\n4,keep,3\n",
                        "id,name,qty\n1,alpha,5\n3,gamma,1\n4,keep,3\n")
        result = compare_files(self.before, self.after, "id")
        data = result.as_dict()
        self.assertEqual(data["summary"], {"added": 1, "removed": 1, "changed": 1, "unchanged": 1})
        self.assertEqual(data["added"][0]["id"], "3")
        self.assertEqual(data["removed"][0]["id"], "2")
        self.assertEqual(data["changed"][0]["fields"], [{"field": "qty", "before": "2", "after": "5"}])

    def test_header_order_does_not_change_result(self):
        self.write_pair("id,name\n1,a\n", "name,id\na,1\n")
        result = compare_files(self.before, self.after, "id")
        self.assertEqual(result.unchanged_count, 1)
        self.assertEqual(result.columns, ("id", "name"))

    def test_duplicate_keys_are_rejected(self):
        self.write_pair("id,x\n1,a\n1,b\n", "id,x\n1,a\n")
        with self.assertRaisesRegex(CsvDiffError, "duplicate key"):
            compare_files(self.before, self.after, "id")

    def test_missing_key_column_is_rejected(self):
        self.write_pair("name\na\n", "name\na\n")
        with self.assertRaisesRegex(CsvDiffError, "key column"):
            compare_files(self.before, self.after, "id")

    def test_schema_drift_is_reported(self):
        self.write_pair("id,name\n1,a\n", "id,title\n1,a\n")
        with self.assertRaisesRegex(CsvDiffError, "schemas differ"):
            compare_files(self.before, self.after, "id")

    def test_wrong_field_count_is_rejected(self):
        self.write_pair("id,name\n1,a,extra\n", "id,name\n1,a\n")
        with self.assertRaisesRegex(CsvDiffError, "different number of fields"):
            compare_files(self.before, self.after, "id")

    def test_duplicate_headers_are_rejected(self):
        self.before.write_text("id,id\n1,2\n", encoding="utf-8")
        with self.assertRaisesRegex(CsvDiffError, "duplicate column"):
            read_csv(self.before, "id")

    def test_bom_and_quoted_newlines_are_supported(self):
        self.write_pair("\ufeffid,note\n1,\"first line\nsecond line\"\n", "id,note\n1,changed\n")
        result = compare_files(self.before, self.after, "id")
        self.assertEqual(result.changed[0]["fields"][0]["before"], "first line\nsecond line")

    def test_markdown_escapes_untrusted_cell_markup(self):
        self.write_pair("id,text\n1,old\n", "id,text\n1,\"<script>|x</script>\"\n")
        report = render_markdown(compare_files(self.before, self.after, "id"))
        self.assertNotIn("<script>", report)
        self.assertIn("&lt;script&gt;", report)
        self.assertIn("\\|", report)
        self.assertNotIn("\\\\|", report)

    def test_json_is_deterministic_and_unicode_friendly(self):
        self.write_pair("id,name\n2,старый\n1,тот же\n", "id,name\n1,тот же\n2,новый\n")
        first = render_json(compare_files(self.before, self.after, "id"))
        second = render_json(compare_files(self.before, self.after, "id"))
        self.assertEqual(first, second)
        self.assertIn("новый", first)
        self.assertEqual(json.loads(first)["summary"]["changed"], 1)

    def test_size_limit_is_enforced(self):
        self.write_pair("id,x\n1,too long\n", "id,x\n1,ok\n")
        with self.assertRaisesRegex(CsvDiffError, "exceeds"):
            compare_files(self.before, self.after, "id", max_bytes=5)

    def test_cli_fail_on_changes_exit_code(self):
        self.write_pair("id,x\n1,a\n", "id,x\n1,b\n")
        result = subprocess.run([sys.executable, "-m", "csv_key_diff.cli", str(self.before), str(self.after), "--key", "id", "--fail-on-changes"],
                                cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Changed fields", result.stdout)

    def test_cli_refuses_to_overwrite_input(self):
        self.write_pair("id,x\n1,a\n", "id,x\n1,b\n")
        result = subprocess.run([sys.executable, "-m", "csv_key_diff.cli", str(self.before), str(self.after), "--key", "id", "--output", str(self.before)],
                                cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("must not overwrite", result.stderr)


if __name__ == "__main__":
    unittest.main()
