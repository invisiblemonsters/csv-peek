# csv-peek

Peek at CSV files from the terminal — pretty aligned tables, JSON output, and quick column stats.
Single file, zero dependencies, Python 3.8+.

```
python csv_peek.py example.csv
```

```
name       city       score  notes
---------  ---------  -----  ------------------
Ada        London      97.5  first programmer
Grace      New York      95  coined "debugging"
Alan       Cambridge  88.25  Turing test
Katherine  Hampton     99.5  orbital mechanics
```

## Features

- Aligned table view with a row cap (default 20; use `-n 0` for all rows)
- Numeric columns are right-aligned automatically, text columns left-aligned
- Column selection by position, e.g. `-c 1,3-5` (order preserved, duplicates dropped)
- `--json` for piping into other tools; `--stats` for per-column summary
- Handles quoted fields with commas / quotes / embedded newlines, ragged rows,
  UTF-8 BOMs from Excel exports, and `\t` delimiters

## Usage

Per-column stats — count, blanks, min, max, mean (numeric columns only):

```
python csv_peek.py example.csv --stats
```

```
column  count  blanks  min    max   mean
------  -----  ------  -----  ----  -------
name        4       0  -      -     -
city        4       0  -      -     -
score       4       0  88.25  99.5  95.0625
notes       4       0  -      -     -
```

JSON output (values kept as strings; use `-n 0` for every row):

```
python csv_peek.py example.csv --json -n 2
```

```
[
  {
    "name": "Ada",
    "city": "London",
    "score": "97.5",
    "notes": "first programmer"
  },
  {
    "name": "Grace",
    "city": "New York",
    "score": "95",
    "notes": "coined \"debugging\""
  }
]
```

Pick columns by position:

```
python csv_peek.py example.csv -c 1,3 -n 2
```

```
name   score
-----  -----
Ada     97.5
Grace     95
... (2 more rows)
```

Treat the first row as data, or use a different delimiter:

```
python csv_peek.py data.csv --no-header
python csv_peek.py data.tsv -d '\t'
```

## Options

```
path                path to the CSV file
-n, --rows N        max data rows to show, 0 = all (default 20)
-c, --cols SPEC     columns to show (1-based), e.g. 1,3-5
-d, --delimiter C   field delimiter; use '\t' for tab (default ,)
--no-header         treat the first row as data (columns get names col1, col2, ...)
--json              print JSON instead of a table
--stats             print per-column stats; uses every row
```

## Tests

```
python -m unittest test_csv_peek.py -v
```

44 tests: parsing (quotes, embedded newlines, delimiters), ragged rows, column-spec
edge cases, alignment, JSON round trips, stats, CLI behavior, and a shape sweep
(widths 1-8 x row counts 0-26 x 3 seeds) that round-trips nasty cells — commas,
quotes, CR/LF, tabs, unicode — through the whole pipeline.

## License

MIT
