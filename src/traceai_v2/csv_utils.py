from __future__ import annotations

import csv
import sys


def configure_csv_field_limit() -> None:
    max_limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(max_limit)
            break
        except OverflowError:
            max_limit = int(max_limit / 10)


configure_csv_field_limit()
