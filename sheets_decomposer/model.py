"""The unified workbook dict every fetcher produces.

workbook = {
  "source": {"type": "sheets|xlsx|export", "id": ..., "url": ..., "path": ..., "fetched_at": iso},
  "properties": {"title", "locale", "time_zone"},
  "drive": {...optional Drive metadata...},
  "named_ranges": [{"name", "sheet", "range"}],
  "sheets": [ {
      "sheet_id", "index", "title", "hidden", "sheet_type", "row_count", "col_count",
      "frozen_rows", "frozen_cols", "tab_color",
      "hidden_rows": [..], "hidden_cols": [..],
      "merges": ["A1:C1", ...],
      "protected_ranges": [{"range", "description", "warning_only"}],
      "validations": [{"a1", "type", "values", "strict", "show_dropdown"}],
      "conditional_formats": [{"ranges": [..], "type", "values"}],
      "charts": [{"title", "type", "source_ranges": [..]}],
      "cells": [ {"a1","row","col","kind","formula","value","formatted","number_format","note","hyperlink"} ]
  } ]
}
kind in: formula | number | string | bool | error | date | empty
Only non-empty cells are stored.
"""
from __future__ import annotations

from datetime import datetime, timezone


def new_workbook(source: dict, title: str = "", locale: str = "", time_zone: str = "") -> dict:
    return {
        "source": {**source, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        "properties": {"title": title, "locale": locale, "time_zone": time_zone},
        "drive": {},
        "named_ranges": [],
        "sheets": [],
    }


def new_sheet(sheet_id, index: int, title: str, **kw) -> dict:
    s = {
        "sheet_id": sheet_id, "index": index, "title": title, "hidden": False, "sheet_type": "GRID",
        "row_count": 0, "col_count": 0, "frozen_rows": 0, "frozen_cols": 0, "tab_color": None,
        "hidden_rows": [], "hidden_cols": [], "merges": [], "protected_ranges": [], "validations": [],
        "conditional_formats": [], "charts": [], "cells": [],
    }
    s.update(kw)
    return s


def new_cell(row: int, col: int, kind: str, formula=None, value=None, formatted=None,
             number_format=None, note=None, hyperlink=None) -> dict:
    from .formulas import a1
    return {
        "a1": a1(row, col), "row": row, "col": col, "kind": kind, "formula": formula, "value": value,
        "formatted": formatted, "number_format": number_format, "note": note, "hyperlink": hyperlink,
    }
