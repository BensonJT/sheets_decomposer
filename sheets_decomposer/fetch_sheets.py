"""Google Sheets API v4 -> unified workbook dict (one spreadsheets.get call)."""
from __future__ import annotations

import re

from .formulas import a1, idx_to_col
from .model import new_cell, new_sheet, new_workbook

SHEET_URL = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")

FIELDS = (
    "spreadsheetId,properties(title,locale,timeZone),"
    "namedRanges(name,range),"
    "sheets("
    "properties(sheetId,index,title,hidden,sheetType,tabColor,gridProperties),"
    "merges,protectedRanges(range,description,warningOnly),"
    "conditionalFormats(ranges,booleanRule(condition)),"
    "charts(chartId,spec(title,basicChart(chartType,domains,series),pieChart)),"
    "data(startRow,startColumn,"
    "rowMetadata(hiddenByUser),columnMetadata(hiddenByUser),"
    "rowData(values(userEnteredValue,effectiveValue,formattedValue,note,hyperlink,"
    "dataValidation,effectiveFormat(numberFormat))))"
    ")"
)


def spreadsheet_id(url_or_id: str) -> str:
    m = SHEET_URL.search(url_or_id)
    if m:
        return m.group(1)
    sid = url_or_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,}", sid):
        raise SystemExit(f"Not a Google Sheets URL or spreadsheet ID: {url_or_id!r}\nExpected https://docs.google.com/spreadsheets/d/<44-char id>/edit")
    return sid


def _grid_range_to_a1(gr: dict, sheet_titles: dict[int, str]) -> str:
    """GridRange (0-based, end-exclusive) -> 'Title!A1:B2'."""
    sr, er = gr.get("startRowIndex"), gr.get("endRowIndex")
    sc, ec = gr.get("startColumnIndex"), gr.get("endColumnIndex")
    def part(r, c):
        return (idx_to_col(c + 1) if c is not None else "") + (str(r + 1) if r is not None else "")
    start = part(sr, sc)
    end = part((er - 1) if er is not None else None, (ec - 1) if ec is not None else None)
    body = start if start == end or not end else f"{start}:{end}"
    title = sheet_titles.get(gr.get("sheetId"), "")
    return f"{title}!{body}" if title else body


def _cell_from_api(row: int, col: int, v: dict) -> dict | None:
    uev = v.get("userEnteredValue") or {}
    eff = v.get("effectiveValue") or {}
    formatted = v.get("formattedValue")
    nf = ((v.get("effectiveFormat") or {}).get("numberFormat") or {})
    number_format = nf.get("pattern") or nf.get("type")
    note, link = v.get("note"), v.get("hyperlink")
    if not uev and not note and not link:
        return None
    if "formulaValue" in uev:
        kind, formula = "formula", uev["formulaValue"]
    elif "numberValue" in uev:
        kind, formula = ("date" if (nf.get("type") in ("DATE", "DATE_TIME", "TIME")) else "number"), None
    elif "boolValue" in uev:
        kind, formula = "bool", None
    elif "errorValue" in uev:
        kind, formula = "error", None
    elif "stringValue" in uev:
        kind, formula = "string", None
    else:
        kind, formula = "empty", None
    # effective value
    if "errorValue" in eff:
        value = eff["errorValue"].get("type", "ERROR")
        value = {"REF": "#REF!", "DIVIDE_BY_ZERO": "#DIV/0!", "N_A": "#N/A", "VALUE": "#VALUE!", "NAME": "#NAME?", "NUM": "#NUM!", "ERROR": "#ERROR!"}.get(value, f"#{value}")
    else:
        value = eff.get("numberValue", eff.get("stringValue", eff.get("boolValue")))
    return new_cell(row, col, kind, formula, value, formatted, number_format, note, link)


def fetch(url_or_id: str, auth_mode: str = "oauth") -> dict:
    from .auth import build_services

    sid = spreadsheet_id(url_or_id)
    sheets, drive = build_services(auth_mode)
    resp = sheets.spreadsheets().get(spreadsheetId=sid, includeGridData=True, fields=FIELDS).execute()

    props = resp.get("properties", {})
    wb = new_workbook(
        {"type": "sheets", "id": sid, "url": f"https://docs.google.com/spreadsheets/d/{sid}/edit", "auth": auth_mode},
        props.get("title", ""), props.get("locale", ""), props.get("timeZone", ""),
    )
    try:
        wb["drive"] = drive.files().get(
            fileId=sid, fields="name,owners(emailAddress,displayName),modifiedTime,createdTime,lastModifyingUser(emailAddress),parents,version"
        ).execute()
    except Exception as e:  # Drive scope may be refused in locked shops; non-fatal
        wb["drive"] = {"error": str(e)[:200]}

    titles = {s["properties"]["sheetId"]: s["properties"]["title"] for s in resp.get("sheets", [])}
    for nr in resp.get("namedRanges", []):
        rng = _grid_range_to_a1(nr["range"], titles)
        sheet, _, body = rng.partition("!") if "!" in rng else ("", "", rng)
        wb["named_ranges"].append({"name": nr["name"], "sheet": sheet, "range": body})

    for s in resp.get("sheets", []):
        p = s["properties"]
        gp = p.get("gridProperties", {})
        tc = p.get("tabColor")
        sh = new_sheet(
            p["sheetId"], p.get("index", 0), p["title"], hidden=p.get("hidden", False), sheet_type=p.get("sheetType", "GRID"),
            row_count=gp.get("rowCount", 0), col_count=gp.get("columnCount", 0),
            frozen_rows=gp.get("frozenRowCount", 0), frozen_cols=gp.get("frozenColumnCount", 0),
            tab_color=(f"#{int(tc.get('red',0)*255):02x}{int(tc.get('green',0)*255):02x}{int(tc.get('blue',0)*255):02x}" if tc else None),
        )
        sh["merges"] = [_grid_range_to_a1(m, {}) for m in s.get("merges", [])]
        sh["protected_ranges"] = [
            {"range": _grid_range_to_a1(pr.get("range", {}), {}) if pr.get("range") else "(sheet)", "description": pr.get("description"), "warning_only": pr.get("warningOnly", False)}
            for pr in s.get("protectedRanges", [])
        ]
        for cf in s.get("conditionalFormats", []):
            cond = (cf.get("booleanRule") or {}).get("condition", {})
            sh["conditional_formats"].append({
                "ranges": [_grid_range_to_a1(r, {}) for r in cf.get("ranges", [])],
                "type": cond.get("type"), "values": [v.get("userEnteredValue") for v in cond.get("values", [])],
            })
        for ch in s.get("charts", []):
            spec = ch.get("spec", {})
            srcs = []
            bc = spec.get("basicChart") or {}
            for d in bc.get("domains", []):
                for r in ((d.get("domain") or {}).get("sourceRange") or {}).get("sources", []):
                    srcs.append(_grid_range_to_a1(r, titles))
            for se in bc.get("series", []):
                for r in ((se.get("series") or {}).get("sourceRange") or {}).get("sources", []):
                    srcs.append(_grid_range_to_a1(r, titles))
            sh["charts"].append({"title": spec.get("title"), "type": bc.get("chartType") or ("PIE" if "pieChart" in spec else "OTHER"), "source_ranges": srcs})

        for gd in s.get("data", []):
            r0, c0 = gd.get("startRow", 0), gd.get("startColumn", 0)
            for i, rm in enumerate(gd.get("rowMetadata", [])):
                if rm.get("hiddenByUser"):
                    sh["hidden_rows"].append(r0 + i + 1)
            for j, cm in enumerate(gd.get("columnMetadata", [])):
                if cm.get("hiddenByUser"):
                    sh["hidden_cols"].append(idx_to_col(c0 + j + 1))
            for i, rd in enumerate(gd.get("rowData", [])):
                for j, v in enumerate(rd.get("values", [])):
                    row, col = r0 + i + 1, c0 + j + 1
                    cell = _cell_from_api(row, col, v)
                    if cell:
                        sh["cells"].append(cell)
                    dv = v.get("dataValidation")
                    if dv:
                        cond = dv.get("condition", {})
                        sh["validations"].append({
                            "a1": a1(row, col), "type": cond.get("type"),
                            "values": [x.get("userEnteredValue") for x in cond.get("values", [])],
                            "strict": dv.get("strict", False), "show_dropdown": dv.get("showCustomUi", False),
                        })
        wb["sheets"].append(sh)
    return wb


def fetch_via_export(url_or_id: str, dest_dir) -> str:
    """No-auth path: download link-shared sheet as xlsx. Returns the file path."""
    import urllib.request
    from pathlib import Path

    sid = spreadsheet_id(url_or_id)
    url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=xlsx"
    dest = Path(dest_dir) / f"{sid}.xlsx"
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        ctype = r.headers.get("Content-Type", "")
        if "html" in ctype:
            raise SystemExit("Export returned HTML, not xlsx: the sheet is not link-shared. Use --auth oauth or share it 'Anyone with the link'.")
        f.write(r.read())
    return str(dest)
