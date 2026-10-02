"""Tests for csv-peek (csv_peek.py)."""

import io
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import csv_peek  # noqa: E402


def run_cli(argv):
    """Run csv_peek.main(argv) in-process, capturing stdout/stderr."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = csv_peek.main(argv)
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
    return code, out.getvalue(), err.getvalue()


class ParserTests(unittest.TestCase):
    def test_quoted_fields(self):
        rows = csv_peek.parse_csv('a,"b,c","d""e"\n')
        self.assertEqual(rows, [["a", "b,c", 'd"e']])

    def test_embedded_newline_and_crlf(self):
        rows = csv_peek.parse_csv('"line1\nline2",x\r\ny,z\r\n')
        self.assertEqual(rows, [["line1\nline2", "x"], ["y", "z"]])

    def test_custom_delimiter(self):
        rows = csv_peek.parse_csv("a;b;c\n1;2;3\n", delimiter=";")
        self.assertEqual(rows, [["a", "b", "c"], ["1", "2", "3"]])

    def test_empty_text(self):
        self.assertEqual(csv_peek.parse_csv(""), [])

    def test_blank_line_yields_empty_row(self):
        rows = csv_peek.parse_csv("a,b\n\nc,d\n")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1], [])


class SplitHeaderTests(unittest.TestCase):
    def test_pads_ragged_rows(self):
        header, data = csv_peek.split_header([["a", "b"], ["1"], ["2", "3", "4"]])
        self.assertEqual(header, ["a", "b", "col3"])
        self.assertEqual(data, [["1", "", ""], ["2", "3", "4"]])

    def test_empty_header_cell_gets_name(self):
        header, data = csv_peek.split_header([["a", ""], ["1", "2"]])
        self.assertEqual(header, ["a", "col2"])
        self.assertEqual(data, [["1", "2"]])

    def test_no_header(self):
        header, data = csv_peek.split_header([["1", "2"], ["3", "4"]], no_header=True)
        self.assertEqual(header, ["col1", "col2"])
        self.assertEqual(data, [["1", "2"], ["3", "4"]])

    def test_empty(self):
        self.assertEqual(csv_peek.split_header([]), ([], []))


class ColSpecTests(unittest.TestCase):
    def test_valid_specs(self):
        cases = {
            "1": [0],
            "1,3": [0, 2],
            "2-4": [1, 2, 3],
            "3-3": [2],
            "2,1": [1, 0],
            "1,3,1": [0, 2],
            "1, 4": [0, 3],
            "1-4": [0, 1, 2, 3],
        }
        for spec, expected in cases.items():
            with self.subTest(spec=spec):
                self.assertEqual(csv_peek.parse_col_spec(spec, 4), expected)

    def test_errors(self):
        bad_specs = ["0", "5", "3-5", "5-3", "a", "", "1,,2", "1-", "-2"]
        for spec in bad_specs:
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError):
                    csv_peek.parse_col_spec(spec, 4)

    def test_no_columns(self):
        with self.assertRaises(ValueError):
            csv_peek.parse_col_spec("1", 0)

    def test_select_columns(self):
        header = ["a", "b", "c"]
        data = [["1", "2", "3"], ["4", "5", "6"]]
        self.assertEqual(
            csv_peek.select_columns(header, data, [2, 0]),
            (["c", "a"], [["3", "1"], ["6", "4"]]),
        )


class PrettyTableTests(unittest.TestCase):
    def test_numeric_column_right_aligned(self):
        table = csv_peek.pretty_table(["n"], [["1"], ["23"]])
        self.assertEqual(table, " n\n--\n 1\n23")

    def test_text_column_left_aligned(self):
        table = csv_peek.pretty_table(["x"], [["a"], ["bcd"]])
        self.assertEqual(table, "x\n---\na\nbcd")

    def test_two_columns_alignment_and_widths(self):
        table = csv_peek.pretty_table(["name", "age"], [["ann", "7"], ["bob", "42"]])
        lines = table.split("\n")
        self.assertEqual(len(lines), 4)
        for line in lines:
            self.assertEqual(len(line), 9)
        self.assertEqual(lines[0], "name  age")
        self.assertEqual(lines[1], "----  ---")
        self.assertEqual(lines[2][:4], "ann ")
        self.assertEqual(lines[2][4:6], "  ")
        self.assertEqual(lines[2][6:], "  7")
        self.assertEqual(lines[3][:4], "bob ")
        self.assertEqual(lines[3][6:], " 42")

    def test_footer_singular_and_plural(self):
        one = csv_peek.pretty_table(["a"], [["1"], ["2"], ["3"]], row_limit=2)
        self.assertTrue(one.endswith("... (1 more row)"))
        two = csv_peek.pretty_table(["a"], [["1"], ["2"], ["3"]], row_limit=1)
        self.assertTrue(two.endswith("... (2 more rows)"))

    def test_no_footer_when_all_rows_shown(self):
        table = csv_peek.pretty_table(["a"], [["1"], ["2"]], row_limit=2)
        self.assertNotIn("more row", table)
        table_all = csv_peek.pretty_table(["a"], [["1"], ["2"]])
        self.assertEqual(len(table_all.split("\n")), 4)

    def test_header_only(self):
        self.assertEqual(csv_peek.pretty_table(["a", "b"], []), "a  b\n-  -")

    def test_blank_cells_do_not_break_numeric_alignment(self):
        table = csv_peek.pretty_table(["n"], [["1"], [""], ["23"]])
        lines = table.split("\n")
        self.assertEqual(lines[0], " n")
        self.assertEqual(lines[2], " 1")
        self.assertEqual(lines[3], "")
        self.assertEqual(lines[4], "23")


class JsonTests(unittest.TestCase):
    def test_json_output(self):
        text = csv_peek.to_json(["a", "b"], [["1", "x"], ["2", "y"]])
        self.assertEqual(json.loads(text), [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}])

    def test_json_keeps_unicode(self):
        text = csv_peek.to_json(["café"], [["é中"]])
        self.assertIn("é中", text)

    def test_json_empty(self):
        self.assertEqual(json.loads(csv_peek.to_json(["a"], [])), [])


class StatsTests(unittest.TestCase):
    def test_stats_mixed_columns(self):
        stats = csv_peek.column_stats(
            ["v", "w"], [["1", "5"], ["2.5", ""], ["", "7"], ["x", "9"]]
        )
        self.assertEqual(stats[0], {"column": "v", "count": 3, "blanks": 1})
        self.assertNotIn("min", stats[0])
        self.assertEqual(stats[1]["count"], 3)
        self.assertEqual(stats[1]["blanks"], 1)
        self.assertEqual(stats[1]["min"], 5.0)
        self.assertEqual(stats[1]["max"], 9.0)
        self.assertAlmostEqual(stats[1]["mean"], 7.0)

    def test_stats_all_blank_column(self):
        stats = csv_peek.column_stats(["v"], [[""], [""]])
        self.assertEqual(stats[0]["count"], 0)
        self.assertEqual(stats[0]["blanks"], 2)
        self.assertNotIn("min", stats[0])

    def test_render_stats(self):
        table = csv_peek.render_stats(
            csv_peek.column_stats(["v"], [["1"], ["2"], ["3"]])
        )
        lines = table.split("\n")
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[-1].split(), ["v", "3", "0", "1", "3", "2"])


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def write(self, text, name="data.csv", encoding="utf-8"):
        path = os.path.join(self._tmp.name, name)
        with open(path, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
        return path

    def test_table_default_and_row_cap(self):
        path = self.write("v\n" + "\n".join(str(i) for i in range(25)) + "\n")
        code, out, err = run_cli([path])
        self.assertEqual(code, 0, err)
        self.assertIn("... (5 more rows)", out)
        shown = [p for p in out.split("\n") if p and not p.startswith("...")]
        self.assertEqual(len(shown), 22)

    def test_rows_zero_shows_all(self):
        path = self.write("v\n" + "\n".join(str(i) for i in range(25)) + "\n")
        code, out, _ = run_cli([path, "-n", "0"])
        self.assertEqual(code, 0)
        self.assertNotIn("more row", out)
        self.assertIn("24", out)

    def test_cols_selection_json(self):
        path = self.write("a,b,c\n1,2,3\n4,5,6\n")
        code, out, _ = run_cli([path, "--json", "-c", "3,1", "-n", "0"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [{"c": "3", "a": "1"}, {"c": "6", "a": "4"}])

    def test_cols_out_of_bounds(self):
        path = self.write("a,b\n1,2\n")
        code, out, err = run_cli([path, "-c", "5"])
        self.assertEqual(code, 2)
        self.assertIn("out of bounds", err)

    def test_bad_delimiter(self):
        path = self.write("a,b\n1,2\n")
        code, _, err = run_cli([path, "-d", "||"])
        self.assertEqual(code, 2)

    def test_negative_rows(self):
        path = self.write("a\n1\n")
        code, _, err = run_cli([path, "-n", "-1"])
        self.assertEqual(code, 2)

    def test_missing_file(self):
        code, _, err = run_cli([os.path.join(self._tmp.name, "nope.csv")])
        self.assertEqual(code, 2)
        self.assertIn("no such file", err)

    def test_empty_file(self):
        path = self.write("")
        code, out, _ = run_cli([path])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "(empty file)")
        code, out, _ = run_cli([path, "--json"])
        self.assertEqual(out.strip(), "[]")

    def test_bom_tolerated(self):
        path = self.write("name,v\nAda,1\n", encoding="utf-8-sig")
        code, out, _ = run_cli([path, "--json"])
        self.assertEqual(json.loads(out), [{"name": "Ada", "v": "1"}])

    def test_no_header(self):
        path = self.write("1,2\n3,4\n")
        code, out, _ = run_cli([path, "--json", "--no-header", "-n", "0"])
        self.assertEqual(
            json.loads(out),
            [{"col1": "1", "col2": "2"}, {"col1": "3", "col2": "4"}],
        )

    def test_tab_delimiter_escape(self):
        path = self.write("a\tb\n1\t2\n")
        code, out, _ = run_cli([path, "--json", "-d", "\\t"])
        self.assertEqual(json.loads(out), [{"a": "1", "b": "2"}])

    def test_json_respects_row_limit(self):
        path = self.write("v\n" + "\n".join(str(i) for i in range(30)) + "\n")
        code, out, _ = run_cli([path, "--json"])
        self.assertEqual(len(json.loads(out)), 20)
        code, out, _ = run_cli([path, "--json", "-n", "0"])
        self.assertEqual(len(json.loads(out)), 30)

    def test_json_and_stats_conflict(self):
        path = self.write("a\n1\n")
        code, _, err = run_cli([path, "--json", "--stats"])
        self.assertEqual(code, 2)

    def test_stats_cli(self):
        path = self.write("v\n1\n2\n3\n")
        code, out, _ = run_cli([path, "--stats"])
        self.assertEqual(code, 0)
        lines = out.strip().split("\n")
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[-1].split(), ["v", "3", "0", "1", "3", "2"])

    def test_version(self):
        code, out, _ = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("csv-peek", out)

    def test_deterministic_output(self):
        path = self.write('a,b\n"x,1",2\n3,4\n')
        _, out1, _ = run_cli([path, "--json", "-n", "0"])
        _, out2, _ = run_cli([path, "--json", "-n", "0"])
        self.assertEqual(out1, out2)

    def test_subprocess_smoke(self):
        path = self.write("name,ciudad\nAda,León\n")
        proc = subprocess.run(
            [sys.executable, os.path.join(HERE, "csv_peek.py"), path, "--json"],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), [{"name": "Ada", "ciudad": "León"}])


class SweepTests(unittest.TestCase):
    """Round-trip the whole pipeline over many shapes with nasty cells."""

    ATOMS = ["a", "b", "Z", "0", "9", " ", ".", "-", "_", "é", "中", "'", "\t"]
    SPLITTERS = [",", '"', "\n", "\r"]

    @classmethod
    def _random_cell(cls, rng):
        parts = []
        for _ in range(rng.randrange(0, 5)):
            parts.append(rng.choice(cls.ATOMS))
            if rng.random() < 0.3:
                parts.append(rng.choice(cls.SPLITTERS))
        return "".join(parts)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_sweep_shapes(self):
        import csv as _csv

        for width in range(1, 9):
            for nrows in (0, 1, 2, 3, 7, 15, 26):
                for seed in range(3):
                    tag = f"w{width}_r{nrows}_s{seed}"
                    with self.subTest(tag):
                        rng = random.Random(width * 10000 + nrows * 100 + seed)
                        header = [
                            self._random_cell(rng) or f"col{i + 1}"
                            for i in range(width)
                        ]
                        data = []
                        for _ in range(nrows):
                            row = [self._random_cell(rng) for _ in range(width)]
                            if rng.random() < 0.25 and width > 1:
                                row = row[: rng.randrange(0, width)]
                            data.append(row)
                        padded = [row + [""] * (width - len(row)) for row in data]

                        path = os.path.join(self._tmp.name, f"{tag}.csv")
                        with open(path, "w", encoding="utf-8", newline="") as fh:
                            writer = _csv.writer(fh)
                            writer.writerow(header)
                            writer.writerows(data)

                        # JSON: full round trip against the generated truth.
                        code, out, err = run_cli([path, "--json", "-n", "0"])
                        self.assertEqual(code, 0, err)
                        expected = [dict(zip(header, row)) for row in padded]
                        self.assertEqual(json.loads(out), expected)

                        # Column selection round trip.
                        if width >= 2:
                            cols = rng.sample(
                                range(1, width + 1), rng.randrange(1, width + 1)
                            )
                            spec = ",".join(map(str, cols))
                            code, out, err = run_cli(
                                [path, "--json", "-n", "0", "-c", spec]
                            )
                            self.assertEqual(code, 0, err)
                            exp_header = [header[c - 1] for c in cols]
                            exp_rows = [
                                [row[c - 1] for c in cols] for row in padded
                            ]
                            self.assertEqual(
                                json.loads(out),
                                [dict(zip(exp_header, r)) for r in exp_rows],
                            )

                        # Pretty table: exact physical line count, even with
                        # embedded newlines inside cells.
                        shown = padded[:3]
                        hidden = max(0, nrows - 3)
                        embedded = sum(c.count("\n") for c in header)
                        embedded += sum(
                            c.count("\n") for row in shown for c in row
                        )
                        code, out, err = run_cli([path, "-n", "3"])
                        self.assertEqual(code, 0, err)
                        pieces = 3 + len(shown) + (1 if hidden else 0) + embedded
                        self.assertEqual(len(out.split("\n")), pieces)

                        # Stats: blank/count bookkeeping against the truth.
                        parsed_header, parsed_data = csv_peek.split_header(
                            csv_peek.read_csv_file(path)
                        )
                        stats = csv_peek.column_stats(parsed_header, parsed_data)
                        for i, entry in enumerate(stats):
                            blanks = sum(1 for row in padded if row[i] == "")
                            self.assertEqual(entry["blanks"], blanks)
                            self.assertEqual(entry["count"], nrows - blanks)


if __name__ == "__main__":
    unittest.main(verbosity=2)
