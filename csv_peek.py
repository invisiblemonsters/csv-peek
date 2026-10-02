#!/usr/bin/env python3
"""csv-peek: peek at CSV files from the terminal.

A zero-dependency CLI that renders CSV files as pretty aligned tables,
prints them as JSON, or summarizes every column with quick stats.

Examples:
    python csv_peek.py data.csv
    python csv_peek.py data.csv -n 0 --json
    python csv_peek.py data.csv -c 1,3-5
    python csv_peek.py data.csv --stats
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys

__version__ = "1.0.0"


# ---------------------------------------------------------------------------
# Reading and shaping
# ---------------------------------------------------------------------------

def parse_csv(text, delimiter=","):
    """Parse CSV text and return a list of rows (lists of strings)."""
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    return list(reader)


def read_csv_file(path, delimiter=","):
    """Read a CSV file as a list of rows. UTF-8 assumed; a BOM is tolerated."""
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh, delimiter=delimiter))


def split_header(rows, no_header=False):
    """Split raw rows into (header, data) and pad ragged rows to full width.

    Empty header cells are named colN. With no_header=True the first row is
    data too and every column is named colN.
    """
    width = max((len(row) for row in rows), default=0)
    if width == 0:
        return [], []
    padded = [row + [""] * (width - len(row)) for row in rows]
    if no_header:
        return [f"col{i}" for i in range(1, width + 1)], padded
    header = [name if name else f"col{i}" for i, name in enumerate(padded[0], 1)]
    return header, padded[1:]


def parse_col_spec(spec, ncols):
    """Parse a 1-based column spec like '1,3-5' into 0-based indices.

    Order is preserved and duplicates are dropped.
    """
    if ncols < 1:
        raise ValueError("no columns available to select")
    indices = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"empty column in {spec!r}")
        if "-" in part:
            lo_text, _, hi_text = part.partition("-")
            try:
                lo, hi = int(lo_text), int(hi_text)
            except ValueError:
                raise ValueError(f"bad range {part!r}") from None
            if lo > hi:
                raise ValueError(f"bad range {part!r}: start greater than end")
            if lo < 1 or hi > ncols:
                raise ValueError(f"range {part!r} out of bounds (columns 1-{ncols})")
            indices.extend(range(lo - 1, hi))
        else:
            try:
                col = int(part)
            except ValueError:
                raise ValueError(f"bad column {part!r}") from None
            if col < 1 or col > ncols:
                raise ValueError(f"column {col} out of bounds (columns 1-{ncols})")
            indices.append(col - 1)
    seen, ordered = set(), []
    for i in indices:
        if i not in seen:
            seen.add(i)
            ordered.append(i)
    return ordered


def select_columns(header, data, indices):
    """Return (header, data) restricted to the given 0-based column indices."""
    return (
        [header[i] for i in indices],
        [[row[i] for i in indices] for row in data],
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _is_numeric(cells):
    """True if every non-empty cell parses as a number and at least one does."""
    seen = False
    for cell in cells:
        if cell == "":
            continue
        try:
            float(cell)
        except ValueError:
            return False
        seen = True
    return seen


def _fmt_row(cells, widths, numeric):
    parts = []
    for cell, width, is_num in zip(cells, widths, numeric):
        parts.append(cell.rjust(width) if is_num else cell.ljust(width))
    return "  ".join(parts)


def pretty_table(header, data, row_limit=None):
    """Render an aligned ASCII table. row_limit=None shows every row."""
    if row_limit is None or row_limit >= len(data):
        shown, hidden = data, 0
    else:
        shown, hidden = data[:row_limit], len(data) - row_limit
    if not header:
        return "(empty file)"
    widths = [len(name) for name in header]
    for row in shown:
        for i, cell in enumerate(row):
            if len(cell) > widths[i]:
                widths[i] = len(cell)
    numeric = [_is_numeric([row[i] for row in data]) for i in range(len(header))]
    lines = [_fmt_row(header, widths, numeric)]
    lines.append("  ".join("-" * width for width in widths))
    for row in shown:
        lines.append(_fmt_row(row, widths, numeric))
    if hidden:
        lines.append(f"... ({hidden} more row{'' if hidden == 1 else 's'})")
    return "\n".join(line.rstrip(" ") for line in lines)


def to_json(header, data):
    """Serialize rows as a JSON array of objects (values kept as strings)."""
    records = [dict(zip(header, row)) for row in data]
    return json.dumps(records, indent=2, ensure_ascii=False)


def column_stats(header, data):
    """Per-column count, blanks, and (when numeric) min / max / mean."""
    stats = []
    for i, name in enumerate(header):
        cells = [row[i] for row in data]
        filled = [cell for cell in cells if cell != ""]
        entry = {"column": name, "count": len(filled),
                 "blanks": len(cells) - len(filled)}
        if filled and _is_numeric(filled):
            values = [float(cell) for cell in filled]
            entry["min"] = min(values)
            entry["max"] = max(values)
            entry["mean"] = sum(values) / len(values)
        stats.append(entry)
    return stats


def render_stats(stats):
    """Render column_stats() output as an aligned table."""
    header = ["column", "count", "blanks", "min", "max", "mean"]
    rows = []
    for entry in stats:
        if "mean" in entry:
            rows.append([
                entry["column"],
                str(entry["count"]),
                str(entry["blanks"]),
                f"{entry['min']:g}",
                f"{entry['max']:g}",
                f"{entry['mean']:g}",
            ])
        else:
            rows.append([
                entry["column"],
                str(entry["count"]),
                str(entry["blanks"]),
                "-", "-", "-",
            ])
    return pretty_table(header, rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _enable_utf8_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def build_parser():
    parser = argparse.ArgumentParser(
        prog="csv-peek",
        description="Peek at CSV files: pretty tables, JSON output, and column stats.",
    )
    parser.add_argument("path", help="path to the CSV file")
    parser.add_argument("-n", "--rows", type=int, default=20, metavar="N",
                        help="max data rows to show, 0 = all (default 20)")
    parser.add_argument("-c", "--cols", metavar="SPEC",
                        help="columns to show (1-based), e.g. 1,3-5")
    parser.add_argument("-d", "--delimiter", default=",", metavar="CHAR",
                        help="field delimiter; use '\\t' for tab (default ',')")
    parser.add_argument("--no-header", action="store_true",
                        help="treat the first row as data (columns get names col1, col2, ...)")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="print JSON instead of a table")
    parser.add_argument("--stats", action="store_true",
                        help="print per-column stats; uses every row")
    parser.add_argument("--version", action="version", version=f"csv-peek {__version__}")
    return parser


def main(argv=None):
    _enable_utf8_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)

    delimiter = "\t" if args.delimiter == "\\t" else args.delimiter
    if len(delimiter) != 1:
        parser.error("delimiter must be a single character (use '\\t' for tab)")
    if args.rows < 0:
        parser.error("-n/--rows must be 0 (all rows) or a positive number")
    if args.stats and args.as_json:
        parser.error("choose one of --json or --stats")

    try:
        rows = read_csv_file(args.path, delimiter)
    except FileNotFoundError:
        print(f"csv-peek: no such file: {args.path}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"csv-peek: cannot read {args.path}: {exc}", file=sys.stderr)
        return 2

    header, data = split_header(rows, args.no_header)

    if args.cols is not None:
        try:
            indices = parse_col_spec(args.cols, len(header))
        except ValueError as exc:
            print(f"csv-peek: bad --cols value: {exc}", file=sys.stderr)
            return 2
        header, data = select_columns(header, data, indices)

    if not header:
        print("[]" if args.as_json else "(empty file)")
        return 0

    if args.stats:
        print(render_stats(column_stats(header, data)))
        return 0

    limit = None if args.rows == 0 else args.rows
    if args.as_json:
        print(to_json(header, data if limit is None else data[:limit]))
    else:
        print(pretty_table(header, data, row_limit=limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
