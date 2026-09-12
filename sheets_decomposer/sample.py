"""Generate a synthetic workforce capacity workbook ("Calls & Chats") with seeded defects.

Written as .xlsx so it can be (a) ingested directly, or (b) uploaded to Google
Drive -> "Open with Google Sheets" to practice the URL/API path. A defect key is
written alongside so practice runs can be self-scored.
"""
from __future__ import annotations

import random
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
BUS = ["Primary Care", "Behavioral Health", "Navigation", "Pharmacy"]
BOLD = Font(bold=True)
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")


def build(path: str, seed: int = 7) -> tuple[str, str]:
    rnd = random.Random(seed)
    wb = Workbook()

    # ---- README
    ws = wb.active
    ws.title = "README"
    ws["A1"] = "Calls & Chats Capacity Model (practice copy)"; ws["A1"].font = BOLD
    ws["A3"] = "Purpose: monthly FTE requirement by business unit for the Calls & Chats channel."
    ws["A4"] = "Owner: (left)"
    ws["A5"] = "Last updated: see cell B7 on Assumptions"
    ws["A7"] = "Tabs: Raw_Paste_Volume -> Forecast_Input -> Staffing_Calc -> Schedule_Output; Assumptions and Seasonality feed Staffing_Calc."

    # ---- Raw_Paste_Volume (weekly actuals pasted from an export; some text-numbers)
    ws = wb.create_sheet("Raw_Paste_Volume")
    ws.append(["Week", "BU", "Calls", "Chats", "Total"]); [setattr(c, "font", BOLD) for c in ws[1]]
    for w in range(1, 27):
        for bu in BUS:
            calls, chats = rnd.randint(800, 2400), rnd.randint(200, 900)
            row = [f"2026-W{w:02d}", bu, calls, chats, None]
            ws.append(row)
            r = ws.max_row
            ws.cell(r, 5).value = f"=C{r}+D{r}"
    ws["C15"] = "1,942"   # DEFECT: number stored as text (paste artifact)
    ws["D31"] = "657"     # DEFECT: number stored as text
    ws.freeze_panes = "A2"

    # ---- Assumptions (named ranges; one stale date; one hidden col)
    ws = wb.create_sheet("Assumptions")
    ws["A1"] = "Assumption"; ws["B1"] = "Value"; ws["C1"] = "Source / owner"; [setattr(c, "font", BOLD) for c in ws[1]]
    rows = [
        ("AHT_Call_sec", 540, "WFM, reviewed quarterly"),
        ("AHT_Chat_sec", 780, "WFM, reviewed quarterly"),
        ("Shrinkage", 0.32, "HR + WFM; breaks, PTO, training"),
        ("Occupancy", 0.85, "Target"),
        ("Hours_per_FTE_month", 160, "Finance"),
        ("Attrition_monthly", 0.03, "HR"),
        ("Last_updated", "2025-11-30", "STALE — DEFECT"),
    ]
    for i, (k, v, src) in enumerate(rows, start=2):
        ws.cell(i, 1, k); ws.cell(i, 2, v).fill = INPUT_FILL; ws.cell(i, 3, src)
        if k != "Last_updated":
            wb.defined_names[k] = DefinedName(k, attr_text=f"Assumptions!$B${i}")
    wb.defined_names["Unused_Buffer"] = DefinedName("Unused_Buffer", attr_text="Assumptions!$B$12")  # DEFECT: unused named range
    ws["A12"] = "Buffer_pct"; ws["B12"] = 0.05
    dv = DataValidation(type="decimal", operator="between", formula1="0", formula2="1", showErrorMessage=True)
    ws.add_data_validation(dv); dv.add("B4:B5")

    # ---- Seasonality (factors; one #REF!)
    ws = wb.create_sheet("Seasonality")
    ws.append(["Month"] + MONTHS); [setattr(c, "font", BOLD) for c in ws[1]]
    ws.append(["Factor"] + [1.00, 0.95, 0.92, 0.90, 0.92, 0.95, 1.00, 1.02, 1.05, 1.15, 1.25, 1.20])
    ws.append(["Note", "Open enrollment Oct-Dec; flu season Dec-Feb"])
    ws["B5"] = "Check: avg factor"; ws["C5"] = "=AVERAGE(B2:M2)"
    ws["B6"] = "Prior-year link"; ws["C6"] = "=#REF!*1.1"   # DEFECT: broken reference

    # ---- Forecast_Input (monthly baseline by BU from the time-series team; literal block)
    ws = wb.create_sheet("Forecast_Input")
    ws.append(["BU", "Metric"] + MONTHS); [setattr(c, "font", BOLD) for c in ws[1]]
    for bu in BUS:
        base_c = rnd.randint(4000, 9000); base_h = rnd.randint(1200, 3500)
        ws.append([bu, "Calls"] + [int(base_c * (1 + rnd.uniform(-0.08, 0.08))) for _ in MONTHS])
        ws.append([bu, "Chats"] + [int(base_h * (1 + rnd.uniform(-0.08, 0.08))) for _ in MONTHS])
    for r in range(2, ws.max_row + 1):
        for c in range(3, 15):
            ws.cell(r, c).fill = INPUT_FILL
    ws["A12"] = "Source: baseline time-series forecast, pasted monthly from the forecasting team's file."
    ws["A13"] = "Total check"; ws["C13"] = "=SUM(C2:C9)"; ws["D13"] = "=SUM(D2:D9)"  # incomplete check row (only 2 of 12 months)
    ws.freeze_panes = "C2"

    # ---- Staffing_Calc (the logic; several seeded defects)
    ws = wb.create_sheet("Staffing_Calc")
    ws.append(["BU", "Line"] + MONTHS); [setattr(c, "font", BOLD) for c in ws[1]]
    r = 2
    lines = {}
    for i, bu in enumerate(BUS):
        fr_c, fr_h = 2 + i * 2, 3 + i * 2   # rows on Forecast_Input
        ws.cell(r, 1, bu); ws.cell(r, 2, "Seasonal calls")
        ws.cell(r + 1, 1, bu); ws.cell(r + 1, 2, "Seasonal chats")
        ws.cell(r + 2, 1, bu); ws.cell(r + 2, 2, "Handle hours")
        ws.cell(r + 3, 1, bu); ws.cell(r + 3, 2, "Required FTE")
        for m in range(12):
            col = 3 + m
            L = ws.cell(1, col).column_letter
            ws.cell(r, col, f"=Forecast_Input!{L}{fr_c}*Seasonality!{L}$2")
            ws.cell(r + 1, col, f"=Forecast_Input!{L}{fr_h}*Seasonality!{L}$2")
            ws.cell(r + 2, col, f"=({L}{r}*AHT_Call_sec+{L}{r+1}*AHT_Chat_sec)/3600")
            ws.cell(r + 3, col, f"={L}{r+2}/(Hours_per_FTE_month*(1-Shrinkage)*Occupancy)")
        lines[bu] = r + 3
        r += 5
    # DEFECTS
    ws["F5"] = 42                                    # hard-coded FTE override inside a formula row (Primary Care, Apr)
    ws["F5"].comment = Comment("Manual override per ops lead — DEFECT: hard-coded", "practice")
    ws["I9"] = "=I7*1.05/3600"                       # magic number + wrong logic (Behavioral Health, Jul handle hours)
    ws["K15"] = "=K14/(Hours_per_FTE_month*(1-0.30)*Occupancy)"  # hard-coded shrinkage instead of named range (Navigation, Sep FTE)
    ws["M19"] = "=Forecast_Input!M8*Seasonality!L$2"             # inconsistent: a seasonal-volume formula pasted into the Handle-hours row (Pharmacy, Nov), and it reads Oct's factor
    ws["B24"] = "Total FTE"
    for m in range(12):
        L = ws.cell(1, 3 + m).column_letter
        ws.cell(24, 3 + m, f"=SUM({L}5,{L}10,{L}15,{L}20)")
    ws["B25"] = "Attrition-adjusted"
    for m in range(12):
        L = ws.cell(1, 3 + m).column_letter
        ws.cell(25, 3 + m, f"={L}24*(1+Attrition_monthly)")
    ws["B26"] = "Peak lookup"; ws["C26"] = '=INDIRECT("Staffing_Calc!"&C27&"24")'; ws["C27"] = "M"   # DEFECT: INDIRECT
    ws["B28"] = "As of"; ws["C28"] = "=TODAY()"      # volatile
    ws.freeze_panes = "C2"

    # ---- Schedule_Output (consumed by scheduling; one IMPORTRANGE in; chart-like summary)
    ws = wb.create_sheet("Schedule_Output")
    ws.append(["Month", "Total FTE", "Attrition-adj FTE", "Rounded HC", "External benchmark"]); [setattr(c, "font", BOLD) for c in ws[1]]
    for m in range(12):
        L = chr(ord("C") + m)
        ws.append([MONTHS[m], f"=Staffing_Calc!{L}24", f"=Staffing_Calc!{L}25", f"=ROUNDUP(C{m+2},0)", None])
    ws["E2"] = '=IMPORTRANGE("https://docs.google.com/spreadsheets/d/1BENCHMARKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx/edit","Bench!B2:B13")'  # external dep
    ws["A15"] = "Peak month"; ws["B15"] = "=INDEX(A2:A13,MATCH(MAX(B2:B13),B2:B13,0))"
    ws["A16"] = "Annual avg HC"; ws["B16"] = "=AVERAGE(D2:D13)"

    # ---- Checks (partial)
    ws = wb.create_sheet("Checks")
    ws["A1"] = "Check"; ws["B1"] = "Value"; ws["C1"] = "Status"; [setattr(c, "font", BOLD) for c in ws[1]]
    ws["A2"] = "Raw weekly total (calls)"; ws["B2"] = "=SUM(Raw_Paste_Volume!C:C)"
    ws["A3"] = "Forecast annual calls"; ws["B3"] = "=SUMIF(Forecast_Input!B:B,\"Calls\",Forecast_Input!C:C)"
    ws["A4"] = "Assumptions in range"; ws["B4"] = "=AND(Shrinkage>0,Shrinkage<1,Occupancy>0,Occupancy<=1)"; ws["C4"] = '=IF(B4,"OK","FAIL")'
    ws["A6"] = "TODO: reconcile Staffing_Calc totals to Schedule_Output"

    # ---- Old hidden version (orphan)
    ws = wb.create_sheet("Old_Version_DO_NOT_USE")
    ws.sheet_state = "hidden"
    ws.append(["BU", "FTE (v1)"]); ws.append(["Primary Care", 38]); ws.append(["Behavioral Health", 21]); ws["B5"] = "=SUM(B2:B3)"

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)

    key = out.with_name(out.stem + "_DEFECT_KEY.md")
    key.write_text(
        "# Defect key — sample_calls_chats.xlsx\n\n"
        "Seeded on purpose. Score a practice run against this list.\n\n"
        "| # | Sheet!Cell | Category | What is wrong |\n|---|---|---|---|\n"
        "| 1 | Staffing_Calc!F5 | hardcoded_in_formula_range | literal 42 overrides the Required-FTE formula (Primary Care, Apr) |\n"
        "| 2 | Staffing_Calc!I9 | inconsistent_formula + magic_number | Behavioral Health Jul handle-hours uses `I7*1.05/3600`, drops chats and AHT, adds an unexplained 1.05 |\n"
        "| 3 | Staffing_Calc!K15 | inconsistent_formula + magic_number | shrinkage hard-coded as 0.30 instead of the named range (Navigation, Sep) |\n"
        "| 4 | Staffing_Calc!M19 | inconsistent_formula | Pharmacy **Nov Handle hours** row holds a seasonal-volume formula (`Forecast_Input!M8*Seasonality!L$2`): wrong logic for the row (volume, not hours) AND it reads Oct's factor. Column M = Nov, not Dec |\n"
        "| 5 | Staffing_Calc!C26 | dynamic_reference | INDIRECT builds an address from C27; untraceable |\n"
        "| 6 | Staffing_Calc!C28 | volatile_function | TODAY() |\n"
        "| 7 | Seasonality!C6 | broken_reference / error_value | `=#REF!*1.1` |\n"
        "| 8 | Raw_Paste_Volume!C15, D31 | text_number | numbers stored as text from a paste; the Total column and Checks!B2 silently skip them |\n"
        "| 9 | Schedule_Output!E2 | external_dependency | IMPORTRANGE to a benchmark file nobody owns |\n"
        "| 10 | Old_Version_DO_NOT_USE | hidden_sheet + orphan_sheet | hidden stale copy |\n"
        "| 11 | Assumptions!B8 | stale input | Last_updated 2025-11-30 (not detectable by script; read the labels) |\n"
        "| 12 | Assumptions (Unused_Buffer) | unused_named_range | defined, never referenced |\n"
        "| 13 | Forecast_Input row 13 | missing_checks (partial) | total check covers 2 of 12 months |\n"
        "| 14 | Checks!A6 | missing_checks | reconciliation Staffing_Calc -> Schedule_Output is a TODO |\n"
        "| 15 | Checks!B2 / B3 | whole_column_reference | fine here, but note it |\n"
        "| 16 | README!A5 | stale documentation | says 'see cell B7 on Assumptions'; Last_updated is at B8 (unplanned; the GEM found it on run 1, 2026-09-11) |\n\n"
        "Things the script cannot see and a human must: the staleness in #11, the *semantic* wrongness of #2 (a script flags the pattern break; only reading the line label tells you chats were dropped), and whether #1 was a legitimate business override.\n"
    )
    return str(out), str(key)
