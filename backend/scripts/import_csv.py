"""Import historical laps from a canonical CSV file (format: docs/import-strategy.md).

Usage (from backend/, after `alembic upgrade head`):

    python -m scripts.import_csv sample-data/historical_runs.csv            # dry run
    python -m scripts.import_csv sample-data/historical_runs.csv --commit   # write

The dry run is the default and never persists anything. The whole file is one
transaction: if any row is invalid, nothing is written. The summary is printed
as JSON. Exit codes: 0 success, 1 validation errors (nothing written),
2 unreadable input or unexpected failure (nothing written).
"""

import argparse
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.database import create_db_engine, create_session_factory
from app.services.csv_import import import_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import historical laps from a canonical CSV.")
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--commit", action="store_true", help="Write the data (default: dry run, writes nothing)."
    )
    parser.add_argument("--database-url", default=get_settings().database_url)
    args = parser.parse_args(argv)

    if not args.path.is_file():
        print(f"File not found: {args.path}", file=sys.stderr)
        return 2
    engine = create_db_engine(args.database_url)
    try:
        result = import_csv(create_session_factory(engine), args.path, commit=args.commit)
    except Exception as exc:  # the transaction was rolled back
        print(f"Import FAILED, nothing was written: {type(exc).__name__}", file=sys.stderr)
        return 2
    finally:
        engine.dispose()
    print(json.dumps(result.to_dict(), indent=2, default=str))
    return 1 if result.errors else 0


if __name__ == "__main__":
    sys.exit(main())
