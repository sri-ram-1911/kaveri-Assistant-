"""Tests for the Midstone 2 CSV cleanup and import rules."""
import csv
from datetime import date

from scripts.build_database import parse_date, read_rows


def test_read_rows_trims_fields_parses_dates_and_drops_exact_duplicates(tmp_path):
    fields = ["customer_id", "company_name", "country", "city", "region_id",
              "segment", "joined_on"]
    row = ["C001", "Example Co", " Germany ", " Berlin ", "R1", " Retail ", "31/12/2024"]
    with (tmp_path / "customers.csv").open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(fields)
        writer.writerow(row)
        writer.writerow(row)

    rows, duplicates = read_rows(tmp_path, "customers")

    assert duplicates == 1
    assert rows == [{"customer_id": "C001", "company_name": "Example Co",
                     "country": "Germany", "city": "Berlin", "region_id": "R1",
                     "segment": "Retail", "joined_on": date(2024, 12, 31)}]


def test_parse_date_accepts_iso_and_day_first():
    assert parse_date("2024-02-29", table="orders", column="order_date") == date(2024, 2, 29)
    assert parse_date("29/02/2024", table="orders", column="order_date") == date(2024, 2, 29)
