"""Write the workbook + analysis into DuckDB (tables + views)."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def _df(rows: list[dict], columns: list[str] | None = None) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=columns or [])
    return pd.DataFrame(rows)


def write_duckdb(path: str, wb: dict, an: dict) -> None:
    p = Path(path)
    try:
        if p.exists():
            p.unlink()
        con = duckdb.connect(str(p))
    except (PermissionError, duckdb.IOException) as e:
        raise SystemExit(
            f"Cannot rewrite {p}: {str(e).splitlines()[0]}\n"
            "Close or disconnect any GUI that has this database open, then re-run ingest."
        ) from None

    sheets = _df([{k: v for k, v in s.items() if k not in ("cells", "validations", "protected_ranges", "conditional_formats", "charts", "merges", "hidden_rows", "hidden_cols")} for s in wb["sheets"]])
    cells = _df([{"sheet": s["title"], **c, "value": json.dumps(c["value"]) if isinstance(c["value"], (dict, list)) else (None if c["value"] is None else str(c["value"]))} for s in wb["sheets"] for c in s["cells"]],
                ["sheet", "a1", "row", "col", "kind", "formula", "value", "formatted", "number_format", "note", "hyperlink"])
    named = _df(wb["named_ranges"], ["name", "sheet", "range"])
    validations = _df([{"sheet": s["title"], **v, "values": json.dumps(v["values"])} for s in wb["sheets"] for v in s["validations"]], ["sheet", "a1", "type", "values", "strict", "show_dropdown"])
    protected = _df([{"sheet": s["title"], **v} for s in wb["sheets"] for v in s["protected_ranges"]], ["sheet", "range", "description", "warning_only"])
    condfmt = _df([{"sheet": s["title"], "ranges": json.dumps(v["ranges"]), "type": v["type"], "values": json.dumps(v["values"])} for s in wb["sheets"] for v in s["conditional_formats"]], ["sheet", "ranges", "type", "values"])
    charts = _df([{"sheet": s["title"], "title": v["title"], "type": v["type"], "source_ranges": json.dumps(v["source_ranges"])} for s in wb["sheets"] for v in s["charts"]], ["sheet", "title", "type", "source_ranges"])
    merges = _df([{"sheet": s["title"], "range": m} for s in wb["sheets"] for m in s["merges"]], ["sheet", "range"])

    formulas = _df([{**f, "functions": json.dumps(f["functions"]), "named_ranges": json.dumps(f["named_ranges"]), "magic_numbers": json.dumps(f["magic_numbers"]), "errors_in_text": json.dumps(f["errors_in_text"]), "value": None if f["value"] is None else str(f["value"])} for f in an["formulas"]],
                   ["sheet", "a1", "row", "col", "formula", "r1c1", "functions", "n_refs", "named_ranges", "magic_numbers", "nesting_depth", "length", "has_external", "has_dynamic", "has_volatile", "has_error_handling", "has_whole_column_ref", "errors_in_text", "value"])
    edges = _df(an["edges"], ["from_sheet", "from_a1", "to_sheet", "to_range", "kind", "cells"])
    sheet_edges = _df(an["sheet_edges"], ["from_sheet", "to_sheet", "n_refs"])
    cell_roles = _df(an["cell_roles"], ["sheet", "a1", "row", "col", "kind", "role", "referenced"])
    sheet_summary = _df(an["sheet_summary"])
    patterns = _df(an["patterns"], ["sheet", "axis", "range", "signature", "n_cells", "n_matching", "n_variants", "is_pattern"])
    defects = _df(an["defects"], ["severity", "category", "sheet", "a1", "detail", "formula"])
    functions = _df([{"function": k, "n": v} for k, v in an["functions"].items()], ["function", "n"])
    importranges = _df(an["importranges"], ["sheet", "a1", "source", "spreadsheet_id", "range"])
    workbook = _df([{"title": wb["properties"]["title"], "source_type": wb["source"]["type"], "source_id": wb["source"].get("id"), "url": wb["source"].get("url"), "fetched_at": wb["source"]["fetched_at"], "n_sheets": len(wb["sheets"]), "drive": json.dumps(wb.get("drive", {}))}])

    for col in ("formula", "value", "formatted", "number_format", "note", "hyperlink"):
        cells[col] = cells[col].astype("string")  # all-null columns would otherwise type as INTEGER
    for name, df in {
        "workbook": workbook, "sheets": sheets, "cells": cells, "named_ranges": named, "validations": validations, "protected_ranges": protected,
        "conditional_formats": condfmt, "charts": charts, "merges": merges, "formulas": formulas, "edges": edges, "sheet_edges": sheet_edges,
        "cell_roles": cell_roles, "sheet_summary": sheet_summary, "patterns": patterns, "defects": defects, "functions": functions, "importranges": importranges,
    }.items():
        con.register("_tmp", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM _tmp")
        con.unregister("_tmp")
    if not an["sheet_summary"]:
        pass
    con.execute((SQL_DIR / "views.sql").read_text())
    con.close()


def query(path: str, sql: str) -> pd.DataFrame:
    try:
        con = duckdb.connect(path, read_only=True)
    except duckdb.IOException as e:
        raise SystemExit(
            f"Cannot open {path}: {str(e).splitlines()[0]}\n"
            "DuckDB allows one process at a time. Close or disconnect any GUI (DBeaver, DataGrip, DuckDB CLI) "
            "that has this file open, then retry."
        ) from None
    try:
        return con.execute(sql).df()
    finally:
        con.close()
