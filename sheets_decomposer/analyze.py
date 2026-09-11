"""Derive structure from the unified workbook dict.

Adds to the workbook (in place) and returns an `analysis` dict:
  formulas      one row per formula cell with parsed detail + R1C1 signature
  edges         reference edges (from cell -> to sheet/range)
  sheet_edges   aggregated sheet -> sheet dependency counts
  cell_roles    per cell: input | calc | output | static | label
  sheet_summary per sheet: counts, in/out degree, role
  patterns      formula blocks: (sheet, axis, start..end, signature, count)
  defects       [{severity, category, sheet, a1, detail, formula}]
  graph         topological order, cycles
  functions     function usage counts
"""
from __future__ import annotations

from collections import Counter, defaultdict

import networkx as nx

from .formulas import (DYNAMIC, ERROR, EXTERNAL, LOOKUP, VOLATILE, a1, col_to_idx, idx_to_col, parse_formula)

MAX_EXPAND = 5000  # cells: expand a referenced range to mark inputs only if smaller than this
NUMERIC_STRING = __import__("re").compile(r"^\s*[-+$]?\s*[\d,]+(\.\d+)?\s*%?\s*$")


def _sheet_index(sheet: dict) -> dict[tuple[int, int], dict]:
    return {(c["row"], c["col"]): c for c in sheet["cells"]}


def analyze(wb: dict) -> dict:
    known_names = {n["name"] for n in wb["named_ranges"]}
    titles = [s["title"] for s in wb["sheets"]]
    title_set = set(titles)
    by_title = {s["title"]: s for s in wb["sheets"]}
    idx = {t: _sheet_index(s) for t, s in by_title.items()}

    formulas, edges = [], []
    referenced: set[tuple[str, int, int]] = set()
    ref_cols: dict[str, set[int]] = defaultdict(set)
    ref_rows: dict[str, set[int]] = defaultdict(set)
    func_counter: Counter = Counter()
    sheet_edges: Counter = Counter()
    importranges = []
    defects: list[dict] = []

    def defect(sev, cat, sheet, cell, detail, formula=None):
        defects.append({"severity": sev, "category": cat, "sheet": sheet, "a1": cell, "detail": detail, "formula": formula})

    # ------------------------------------------------ 1. parse every formula
    for s in wb["sheets"]:
        st = s["title"]
        for c in s["cells"]:
            if c["kind"] != "formula":
                continue
            pf = parse_formula(c["formula"], c["row"], c["col"], known_names or None)
            func_counter.update(pf.functions)
            row = {
                "sheet": st, "a1": c["a1"], "row": c["row"], "col": c["col"], "formula": c["formula"], "r1c1": pf.r1c1,
                "functions": pf.functions, "n_refs": len(pf.refs), "named_ranges": pf.named_candidates,
                "magic_numbers": pf.magic_numbers, "nesting_depth": pf.nesting_depth, "length": pf.length,
                "has_external": pf.has_external, "has_dynamic": pf.has_dynamic, "has_volatile": pf.has_volatile,
                "has_error_handling": pf.has_error_handling, "has_whole_column_ref": pf.has_whole_column_ref,
                "errors_in_text": pf.errors_in_text, "value": c["value"],
            }
            formulas.append(row)
            for ir in pf.importranges:
                importranges.append({"sheet": st, "a1": c["a1"], **ir})
                edges.append({"from_sheet": st, "from_a1": c["a1"], "to_sheet": f"[external] {ir.get('spreadsheet_id') or ir['source']}", "to_range": ir["range"], "kind": "external", "cells": None})
            for nm in pf.named_candidates:
                nr = next((n for n in wb["named_ranges"] if n["name"] == nm), None)
                if nr:
                    edges.append({"from_sheet": st, "from_a1": c["a1"], "to_sheet": nr["sheet"] or st, "to_range": nr["range"], "kind": "named", "cells": None})
                    if nr["sheet"] or st:
                        sheet_edges[(st, nr["sheet"] or st)] += 1
                        try:
                            r = __import__("sheets_decomposer.formulas", fromlist=["parse_ref"]).parse_ref(nr["range"].replace("$", ""), nr["sheet"])
                            _mark(r, nr["sheet"] or st, referenced, ref_cols, ref_rows)
                        except Exception:
                            pass
            for r in pf.refs:
                to_sheet = r.sheet or st
                if to_sheet not in title_set:
                    defect("high", "broken_reference", st, c["a1"], f"references sheet '{to_sheet}' which does not exist", c["formula"])
                edges.append({"from_sheet": st, "from_a1": c["a1"], "to_sheet": to_sheet, "to_range": r.rng, "kind": r.kind, "cells": r.cell_count()})
                sheet_edges[(st, to_sheet)] += 1
                _mark(r, to_sheet, referenced, ref_cols, ref_rows)
            if pf.has_dynamic:
                defect("medium", "dynamic_reference", st, c["a1"], f"uses {sorted(set(pf.functions) & DYNAMIC)}: dependencies cannot be traced statically", c["formula"])
            if pf.has_volatile and not pf.has_dynamic:
                defect("low", "volatile_function", st, c["a1"], f"volatile {sorted(set(pf.functions) & VOLATILE)}: recalculates on every edit; result changes by day", c["formula"])
            if pf.errors_in_text:
                defect("high", "broken_reference", st, c["a1"], f"formula text contains {pf.errors_in_text} (a referenced row/column/sheet was deleted)", c["formula"])
            if pf.has_whole_column_ref:
                defect("low", "whole_column_reference", st, c["a1"], "whole-column/row reference; fine for lookups, slow and error-prone inside SUMPRODUCT/ARRAYFORMULA", c["formula"])
            if pf.length > 250 or pf.nesting_depth >= 6:
                defect("low", "complex_formula", st, c["a1"], f"length {pf.length}, nesting depth {pf.nesting_depth}; candidate to split into helper cells", c["formula"])

    # ------------------------------------------------ 2. error values in cells
    for s in wb["sheets"]:
        for c in s["cells"]:
            if isinstance(c["value"], str) and ERROR.fullmatch(c["value"].strip() or "x"):
                defect("high", "error_value", s["title"], c["a1"], f"cell evaluates to {c['value']}", c.get("formula"))
            if c["kind"] == "error":
                defect("high", "error_value", s["title"], c["a1"], f"literal error value {c['value']}", None)

    # ------------------------------------------------ 3. formula pattern consistency (R1C1 runs)
    # A "pattern" is a contiguous run (down a column or across a row) of formula cells whose
    # R1C1 signature is at least 60% identical. Each formula cell is assigned to the axis where
    # it sits in the stronger run, so row-oriented models (months across) and column-oriented
    # models (records down) both collapse to one line per block of logic.
    sig = {(f["sheet"], f["row"], f["col"]): f["r1c1"] for f in formulas}
    candidate_runs = []  # dicts: sheet, axis, key, cells[(pos, sig)], major, n_major
    for s in wb["sheets"]:
        st = s["title"]
        for axis in ("col", "row"):
            groups: dict[int, list[tuple[int, str]]] = defaultdict(list)
            for (sh, r, c), sg in sig.items():
                if sh != st:
                    continue
                key, pos = (c, r) if axis == "col" else (r, c)
                groups[key].append((pos, sg))
            for key, items in groups.items():
                items.sort()
                run: list[tuple[int, str]] = []
                runs = []
                for pos, sg in items:
                    if run and pos != run[-1][0] + 1:
                        runs.append(run); run = []
                    run.append((pos, sg))
                if run:
                    runs.append(run)
                for run in runs:
                    cnt = Counter(sg for _, sg in run)
                    major, n = cnt.most_common(1)[0]
                    candidate_runs.append({"sheet": st, "axis": axis, "key": key, "cells": run, "major": major, "n_major": n, "n_variants": len(cnt)})
    # assign each cell to its strongest run
    best: dict[tuple[str, int, int], tuple[int, int]] = {}  # cell -> (n_major, run_index)
    for i, R in enumerate(candidate_runs):
        for pos, _ in R["cells"]:
            cell = (R["sheet"], pos, R["key"]) if R["axis"] == "col" else (R["sheet"], R["key"], pos)
            if cell not in best or R["n_major"] > best[cell][0]:
                best[cell] = (R["n_major"], i)
    assigned: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for cell, (_, i) in best.items():
        R = candidate_runs[i]
        pos = cell[1] if R["axis"] == "col" else cell[2]
        assigned[i].append((pos, sig[cell]))
    patterns = []
    inconsistent: set[tuple[str, int, int]] = set()
    for i, R in enumerate(candidate_runs):
        cells = sorted(assigned.get(i, []))
        if not cells:
            continue
        cnt = Counter(sg for _, sg in cells)
        major, n = cnt.most_common(1)[0]
        key, st, axis = R["key"], R["sheet"], R["axis"]
        start, end = cells[0][0], cells[-1][0]
        loc = (f"{idx_to_col(key)}{start}:{idx_to_col(key)}{end}" if axis == "col" else f"{idx_to_col(start)}{key}:{idx_to_col(end)}{key}")
        is_pattern = len(cells) >= 3 and n >= max(3, 0.6 * len(cells))
        patterns.append({"sheet": st, "axis": axis, "range": loc, "signature": major, "n_cells": len(cells), "n_matching": n, "n_variants": len(cnt), "is_pattern": is_pattern})
        if is_pattern and len(cnt) > 1:
            for pos, sg in cells:
                if sg != major:
                    inconsistent.add((st, pos, key) if axis == "col" else (st, key, pos))
    patterns.sort(key=lambda p: (p["sheet"], p["axis"], p["range"]))
    for (st, r, c) in sorted(inconsistent):
        f = next(x for x in formulas if x["sheet"] == st and x["row"] == r and x["col"] == c)
        defect("high", "inconsistent_formula", st, a1(r, c), "formula breaks the pattern of its neighbours (R1C1 signature differs from the run's majority)", f["formula"])

    # ------------------------------------------------ 3b. magic numbers, one finding per distinct formula signature
    UNIT_LITERALS = {"3600", "60", "24", "7", "12", "52", "365", "1000", "100", "0.5", "1440", "30", "4", "3"}
    by_sig: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for f in formulas:
        if f["magic_numbers"]:
            by_sig[(f["sheet"], f["r1c1"])].append(f)
    for (st, sg), fs in by_sig.items():
        lits = sorted(set(x for f in fs for x in f["magic_numbers"]))
        unit_only = all(x in UNIT_LITERALS for x in lits)
        first, last = fs[0], fs[-1]
        where = first["a1"] if len(fs) == 1 else f"{first['a1']}..{last['a1']} ({len(fs)} cells)"
        defect("low" if unit_only else "medium", "magic_number", st, where,
               f"literal(s) {lits} embedded in formula" + (" (unit conversion; label it anyway)" if unit_only else "; should be a labelled assumption cell so it can be changed in one place"), first["formula"])

    # ------------------------------------------------ 4. hard-coded values inside formula runs
    for s in wb["sheets"]:
        st = s["title"]
        ix = idx[st]
        for c in s["cells"]:
            if c["kind"] not in ("number", "string"):
                continue
            if c["kind"] == "string" and not NUMERIC_STRING.match(str(c["value"] or "")):
                continue
            r, k = c["row"], c["col"]
            for (dr, dc) in ((1, 0), (0, 1)):
                up = ix.get((r - dr, k - dc)); dn = ix.get((r + dr, k + dc))
                if up and dn and up["kind"] == "formula" and dn["kind"] == "formula":
                    su, sd = sig.get((st, r - dr, k - dc)), sig.get((st, r + dr, k + dc))
                    if su == sd:
                        kind = "text_number" if c["kind"] == "string" else "hardcoded_in_formula_range"
                        defect("high", kind, st, c["a1"], f"literal {c['value']!r} sits inside a run of identical formulas (neighbours {a1(r-dr,k-dc)} and {a1(r+dr,k+dc)}): overwritten formula or manual override", None)
                        break
    # numbers stored as text anywhere in a mostly-numeric column
    for s in wb["sheets"]:
        st = s["title"]
        cols: dict[int, list[dict]] = defaultdict(list)
        for c in s["cells"]:
            cols[c["col"]].append(c)
        for k, cells in cols.items():
            nums = sum(1 for c in cells if c["kind"] in ("number", "formula"))
            for c in cells:
                if c["kind"] == "string" and NUMERIC_STRING.match(str(c["value"] or "")) and nums >= 3:
                    if not any(d["sheet"] == st and d["a1"] == c["a1"] for d in defects):
                        defect("medium", "text_number", st, c["a1"], f"{c['value']!r} is text in a numeric column; SUM/lookups silently skip it", None)

    # ------------------------------------------------ 5. cell roles
    cell_roles = []
    role_counts: dict[str, Counter] = defaultdict(Counter)
    for s in wb["sheets"]:
        st = s["title"]
        for c in s["cells"]:
            is_ref = (st, c["row"], c["col"]) in referenced or c["col"] in ref_cols[st] or c["row"] in ref_rows[st]
            if c["kind"] == "formula":
                role = "calc" if is_ref else "output"
            elif c["kind"] in ("number", "date", "bool"):
                role = "input" if is_ref else "static"
            elif c["kind"] == "string":
                role = "input" if is_ref else "label"
            else:
                role = "other"
            cell_roles.append({"sheet": st, "a1": c["a1"], "row": c["row"], "col": c["col"], "kind": c["kind"], "role": role, "referenced": is_ref})
            role_counts[st][role] += 1

    # ------------------------------------------------ 6. sheet summary + graph
    G = nx.DiGraph()
    for t in titles:
        G.add_node(t)
    for (a, b), n in sheet_edges.items():
        if a != b:
            G.add_edge(a, b, weight=n)  # a depends on b
    chart_sources = {t: sum(len(ch["source_ranges"]) for ch in by_title[t]["charts"]) for t in titles}
    sheet_summary = []
    for s in wb["sheets"]:
        st = s["title"]
        n_cells = len(s["cells"]); n_f = sum(1 for c in s["cells"] if c["kind"] == "formula")
        outdeg = sum(1 for _ in G.successors(st)); indeg = sum(1 for _ in G.predecessors(st))
        rc = role_counts[st]
        ratio = n_f / n_cells if n_cells else 0
        if n_cells == 0:
            role = "empty"
        elif indeg == 0 and outdeg == 0 and chart_sources[st] == 0:
            role = "orphan"
        elif ratio < 0.25 and outdeg == 0:
            role = "input/raw"
        elif ratio >= 0.05 and indeg == 0 and outdeg > 0:
            role = "output"
        elif ratio >= 0.05 and indeg > 0:
            role = "calc"
        elif ratio < 0.05 and outdeg > 0:
            role = "config"
        else:
            role = "mixed"
        sheet_summary.append({
            "sheet": st, "index": s["index"], "hidden": s["hidden"], "role": role, "rows": s["row_count"], "cols": s["col_count"],
            "n_cells": n_cells, "n_formulas": n_f, "n_literals": n_cells - n_f, "formula_ratio": round(ratio, 3),
            "n_inputs": rc["input"], "n_outputs": rc["output"], "feeds": sorted(G.predecessors(st)), "depends_on": sorted(G.successors(st)),
            "n_charts": len(s["charts"]), "n_validations": len(s["validations"]), "n_protected": len(s["protected_ranges"]),
            "hidden_rows": len(s["hidden_rows"]), "hidden_cols": len(s["hidden_cols"]),
        })
        if s["hidden"]:
            defect("medium", "hidden_sheet", st, None, f"sheet is hidden (role={role}, {n_f} formulas); hidden logic is undocumented logic", None)
        if role == "orphan" and n_cells > 0:
            defect("medium", "orphan_sheet", st, None, "nothing references this sheet and it references nothing: stale copy, scratch, or manual output", None)
        if s["hidden_rows"] or s["hidden_cols"]:
            defect("low", "hidden_rows_cols", st, None, f"{len(s['hidden_rows'])} hidden rows, {len(s['hidden_cols'])} hidden columns", None)
    cycles = [c for c in nx.simple_cycles(G)]
    for cyc in cycles:
        defect("high", "circular_reference", " -> ".join(cyc + [cyc[0]]), None, "sheets reference each other in a loop; verify iterative calc is intended", None)
    try:
        order = list(reversed(list(nx.topological_sort(G))))  # sources first
    except nx.NetworkXUnfeasible:
        order = titles
    # missing checks: no error handling and no obvious reconciliation
    n_err = sum(1 for f in formulas if f["has_error_handling"])
    check_words = ("check", "recon", "variance", "diff", "control", "qa")
    has_check_tab = any(any(w in t.lower() for w in check_words) for t in titles)
    if formulas and not has_check_tab:
        defect("medium", "missing_checks", None, None, "no tab named like Check/Recon/Control; no visible reconciliation of inputs to outputs", None)
    if formulas and n_err == 0:
        defect("low", "missing_checks", None, None, "no IFERROR/IFNA/ISERROR anywhere: lookups fail loudly with #N/A and propagate", None)
    unref_names = [n["name"] for n in wb["named_ranges"] if not any(n["name"] in f["named_ranges"] for f in formulas)]
    for nm in unref_names:
        defect("low", "unused_named_range", None, None, f"named range '{nm}' is defined but never used", None)
    for ir in importranges:
        defect("medium", "external_dependency", ir["sheet"], ir["a1"], f"IMPORTRANGE from {ir.get('spreadsheet_id') or ir['source']} range {ir['range']}: silent breakage if source moves or permission lapses", None)

    sev_rank = {"high": 0, "medium": 1, "low": 2}
    defects.sort(key=lambda d: (sev_rank[d["severity"]], d["category"], d["sheet"] or "", d["a1"] or ""))
    return {
        "formulas": formulas, "edges": edges, "sheet_edges": [{"from_sheet": a, "to_sheet": b, "n_refs": n} for (a, b), n in sheet_edges.items()],
        "cell_roles": cell_roles, "sheet_summary": sheet_summary, "patterns": patterns, "defects": defects,
        "graph": {"order_sources_first": order, "cycles": cycles}, "functions": dict(func_counter.most_common()),
        "importranges": importranges,
    }


def _mark(r, to_sheet, referenced, ref_cols, ref_rows):
    if r.kind == "cell":
        referenced.add((to_sheet, r.start_row, r.start_col))
    elif r.kind == "range":
        if (r.cell_count() or 0) <= MAX_EXPAND:
            for rr in range(r.start_row, r.end_row + 1):
                for cc in range(r.start_col, r.end_col + 1):
                    referenced.add((to_sheet, rr, cc))
        else:
            for cc in range(r.start_col, r.end_col + 1):
                ref_cols[to_sheet].add(cc)
    elif r.kind == "cols":
        for cc in range(r.start_col, r.end_col + 1):
            ref_cols[to_sheet].add(cc)
    elif r.kind == "rows":
        for rr in range(r.start_row, r.end_row + 1):
            ref_rows[to_sheet].add(rr)
