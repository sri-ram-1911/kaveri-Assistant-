"""Build the Midstone 2 SQLite database from its supplied raw CSV exports."""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import (Column, Date, ForeignKey, Integer, MetaData, Numeric, String,
                        Table, create_engine, event)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path(r"D:\Midstone 2\data\raw")
DEFAULT_DATABASE = ROOT / "kaveri.db"

SCHEMA: dict[str, list[tuple[str, Any, bool, str | None]]] = {
    "regions": [
        ("region_id", String(8), True, None),
        ("region_name", String(80), False, None),
        ("sales_head", String(120), False, None),
        ("target_2024", Numeric(14, 2), False, None),
    ],
    "customers": [
        ("customer_id", String(12), True, None),
        ("company_name", String(200), False, None),
        ("country", String(100), False, None),
        ("city", String(100), False, None),
        ("region_id", String(8), False, "regions.region_id"),
        ("segment", String(40), False, None),
        ("joined_on", Date(), False, None),
    ],
    "products": [
        ("product_id", String(12), True, None),
        ("product_name", String(200), False, None),
        ("category", String(100), False, None),
        ("list_price", Numeric(14, 2), False, None),
    ],
    "orders": [
        ("order_id", String(16), True, None),
        ("customer_id", String(12), False, "customers.customer_id"),
        ("order_date", Date(), False, None),
        ("status", String(32), False, None),
        ("sales_channel", String(48), False, None),
        ("total_amount", Numeric(14, 2), False, None),
    ],
    "order_items": [
        ("order_item_id", Integer(), True, None),
        ("order_id", String(16), False, "orders.order_id"),
        ("product_id", String(12), False, "products.product_id"),
        ("quantity", Integer(), False, None),
        ("unit_price", Numeric(14, 2), False, None),
        ("line_total", Numeric(14, 2), False, None),
    ],
}
LOAD_ORDER = ("regions", "customers", "products", "orders", "order_items")
DATE_COLUMNS = {"joined_on", "order_date"}
INTEGER_COLUMNS = {"order_item_id", "quantity"}
MONEY_COLUMNS = {"target_2024", "list_price", "total_amount", "unit_price", "line_total"}


def parse_date(value: str, *, table: str, column: str) -> date:
    """Parse the documented ISO dates and raw DD/MM/YYYY variants."""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Invalid {table}.{column} date value: {value!r}")


def read_rows(source: Path, table: str) -> tuple[list[dict[str, Any]], int]:
    """Read a CSV, drop duplicate source rows, trim values, and coerce types."""
    path = source / f"{table}.csv"
    expected = [column for column, *_ in SCHEMA[table]]
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    duplicate_count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None or set(reader.fieldnames) != set(expected):
            raise ValueError(f"Unexpected columns in {path}: {reader.fieldnames!r}; expected {expected!r}")
        for raw in reader:
            if None in raw:
                raise ValueError(f"Unexpected extra CSV values in {path}: {raw!r}")
            exact_key = tuple(raw[column] for column in expected)
            if exact_key in seen:
                duplicate_count += 1
                continue
            seen.add(exact_key)
            row: dict[str, Any] = {}
            for column in expected:
                value = (raw[column] or "").strip()
                if value == "":
                    row[column] = None
                elif column in DATE_COLUMNS:
                    row[column] = parse_date(value, table=table, column=column)
                elif column in INTEGER_COLUMNS:
                    row[column] = int(value)
                elif column in MONEY_COLUMNS:
                    row[column] = Decimal(value)
                else:
                    row[column] = value
            records.append(row)
    return records, duplicate_count


def make_metadata() -> MetaData:
    """Declare the five tables from the Midstone 2 data dictionary."""
    metadata = MetaData()
    for table_name in LOAD_ORDER:
        columns = []
        for name, sql_type, primary_key, foreign_key in SCHEMA[table_name]:
            column_args = [name, sql_type]
            if foreign_key:
                column_args.append(ForeignKey(foreign_key))
            columns.append(Column(*column_args, primary_key=primary_key,
                                  nullable=not primary_key))
        Table(table_name, metadata, *columns)
    return metadata


def build_database(source: Path, database: Path) -> dict[str, dict[str, int]]:
    """Create the local SQLite database; refuse to overwrite an existing file."""
    source = source.resolve()
    database = database.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"CSV source directory does not exist: {source}")
    if database.exists():
        raise FileExistsError(f"Refusing to overwrite existing database: {database}")

    loaded = {name: read_rows(source, name) for name in LOAD_ORDER}
    if len(loaded["customers"][0]) != 128:
        raise ValueError(f"Expected 128 cleaned customers, found {len(loaded['customers'][0])}")

    database.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{database.as_posix()}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:  # type: ignore[no-untyped-def]
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata = make_metadata()
    try:
        metadata.create_all(engine)
        with engine.begin() as connection:
            for table_name in LOAD_ORDER:
                rows, _duplicates = loaded[table_name]
                connection.execute(metadata.tables[table_name].insert(), rows)
    except Exception:
        engine.dispose()
        database.unlink(missing_ok=True)
        raise
    engine.dispose()
    return {name: {"rows": len(rows), "duplicates_dropped": duplicates}
            for name, (rows, duplicates) in loaded.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-dir", type=Path, default=DEFAULT_SOURCE,
                        help="Directory containing regions.csv, customers.csv, etc.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE,
                        help="Output SQLite database path (must not already exist).")
    args = parser.parse_args()
    results = build_database(args.csv_dir, args.database)
    for name, stats in results.items():
        print(f"{name}: {stats['rows']} rows; dropped {stats['duplicates_dropped']} exact duplicates")
    print(f"Created {args.database.resolve()}")


if __name__ == "__main__":
    main()
