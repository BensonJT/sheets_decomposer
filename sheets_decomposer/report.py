"""Markdown outputs: the human report and the compact LLM context."""
from __future__ import annotations

from collections import defaultdict


def _mermaid(an: dict) -> str:
    lines = ["```mermaid", "flowchart LR"]
    ids = {}
    for i, s in enumerate(an["sheet_summary"]):
        ids[s["sheet"]] = f"S{i}"
        label = s["sheet"].replace('"', "'")
        shape = ("[(", ")]") if s["role"] == "input/raw" else (("{{", "}}") if s["role"] == "output" else ("[", "]"))
        style = ":::hidden" if s["hidden"] else ""
        lines.append(f'  {ids[s["sheet"]]}{shape[0]}"{label}<br/>{s["role"]} · {s["n_formulas"]}f"{shape[1]}{style}')
    for e in an["sheet_edges"]:
        if e["from_sheet"] == e["to_sheet"]:
            continue
        if e["to_sheet"] not in ids:
            ids[e["to_sheet"]] = f"X{len(ids)}"
            lines.append(f'  {ids[e["to_sheet"]]}[/"{e["to_sheet"]}"/]')
        lines.append(f'  {ids[e["to_sheet"]]} -- {e["n_refs"]} --> {ids[e["from_sheet"]]}')
    lines.append("  classDef hidden stroke-dasharray: 5 5,opacity:0.6")
    lines.append("```")
    return "\n".join(lines)


def _table(rows: list[dict], cols: list[str]) -> str:
    if not rows:
        return "_none_\n"
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "") if r.get(c) is not None else "").replace("|", "\\|").replace("\n", " ") for c in cols) + " |")
    return "\n".join(out) + "\n"


def _questions(an: dict) -> list[str]:
    qs = []
    seen = set()
    for d in an["defects"]:
        key = (d["category"], d["sheet"])
        if key in seen:
            continue
        seen.add(key)
        loc = f"{d['sheet']}!{d['a1']}" if d["a1"] else (d["sheet"] or "workbook")
        if d["category"] == "hardcoded_in_formula_range":
            qs.append(f"{loc} is a typed number inside a formula column. Intentional override, or an overwrite that was never restored?")
        elif d["category"] == "inconsistent_formula":
            qs.append(f"{loc} computes differently from its neighbours. Is that a deliberate exception? Where is that documented?")
        elif d["category"] == "magic_number":
            qs.append(f"{loc} carries a literal factor in the formula. What is it, who owns it, and when was it last reviewed?")
        elif d["category"] == "external_dependency":
            qs.append(f"{loc} pulls from another spreadsheet via IMPORTRANGE. Who owns that file, and what happens when they restructure it?")
        elif d["category"] == "hidden_sheet":
            qs.append(f"'{d['sheet']}' is hidden. Is it still in use, and who last touched it?")
        elif d["category"] == "orphan_sheet":
            qs.append(f"'{d['sheet']}' is referenced by nothing. Is it a manual output, an archived version, or scratch?")
        elif d["category"] == "error_value":
            qs.append(f"{loc} shows an error. Is the output that reads it currently wrong, and since when?")
        elif d["category"] == "missing_checks":
            qs.append("Where is the reconciliation between the pasted inputs and the reported outputs done today, if anywhere?")
        elif d["category"] == "dynamic_reference":
            qs.append(f"{loc} uses INDIRECT/OFFSET. What is it selecting, and could a plain reference or a lookup do the same job?")
        elif d["category"] == "text_number":
            qs.append(f"{loc} holds a number stored as text. Is that column pasted in from an export, and does anything sum it?")
    return qs[:15]


def write_report(wb: dict, an: dict) -> str:
    ss = an["sheet_summary"]
    n_f = sum(s["n_formulas"] for s in ss)
    n_c = sum(s["n_cells"] for s in ss)
    L = [f"# Workbook decomposition — {wb['properties']['title']}", ""]
    L.append(f"Source: `{wb['source'].get('url') or wb['source'].get('path')}` · fetched {wb['source']['fetched_at']} · {len(ss)} sheets · {n_c:,} populated cells · {n_f:,} formulas · {len(an['defects'])} findings")
    d = wb.get("drive") or {}
    if d and "error" not in d:
        owners = ", ".join(o.get("emailAddress", "") for o in d.get("owners", []))
        L.append(f"Drive: owner {owners} · modified {d.get('modifiedTime')} by {(d.get('lastModifyingUser') or {}).get('emailAddress')} · created {d.get('createdTime')}")
    L += ["", "## 1. Inventory", ""]
    L.append(_table(ss, ["index", "sheet", "role", "hidden", "n_cells", "n_formulas", "formula_ratio", "n_inputs", "n_outputs", "depends_on", "feeds"]))
    L += ["## 2. Flow", "", "Arrows point from source to consumer. Calculation order (sources first): " + " → ".join(an["graph"]["order_sources_first"]), ""]
    if an["graph"]["cycles"]:
        L.append("**Circular sheet references:** " + "; ".join(" → ".join(c) for c in an["graph"]["cycles"]) + "\n")
    L.append(_mermaid(an))
    L += ["", "## 3. Formula patterns (one row per block of identical logic)", ""]
    pats = [p for p in an["patterns"] if p["is_pattern"]]
    L.append(_table(pats, ["sheet", "range", "n_cells", "n_variants", "signature"]))
    singles = [p for p in an["patterns"] if not p["is_pattern"]]
    if singles:
        L.append(f"Plus {sum(p['n_cells'] for p in singles)} formula cells that do not belong to a repeating block (listed in gem_context.md).\n")
    L += ["## 4. Functions used", "", ", ".join(f"{k} ({v})" for k, v in an["functions"].items()) or "_none_", ""]
    L += ["## 5. Named ranges, validations, protections, charts", ""]
    L.append("**Named ranges:** " + (", ".join(f"{n['name']} = {n['sheet']}!{n['range']}" for n in wb["named_ranges"]) or "none") + "\n")
    for s in wb["sheets"]:
        bits = []
        if s["validations"]:
            bits.append(f"{len(s['validations'])} validations")
        if s["protected_ranges"]:
            bits.append(f"{len(s['protected_ranges'])} protected ranges")
        if s["charts"]:
            bits.append("charts: " + "; ".join(f"{c['title'] or c['type']} ← {', '.join(c['source_ranges'])}" for c in s["charts"]))
        if s["conditional_formats"]:
            bits.append(f"{len(s['conditional_formats'])} conditional formats")
        if s["merges"]:
            bits.append(f"{len(s['merges'])} merged ranges")
        if bits:
            L.append(f"- **{s['title']}**: " + " · ".join(bits))
    L += ["", "## 6. External dependencies", ""]
    L.append(_table(an["importranges"], ["sheet", "a1", "spreadsheet_id", "range"]))
    L += ["## 7. Findings (the defect list, JD vocabulary)", ""]
    counts = defaultdict(int)
    for d in an["defects"]:
        counts[(d["severity"], d["category"])] += 1
    L.append(_table([{"severity": k[0], "category": k[1], "n": v} for k, v in sorted(counts.items(), key=lambda kv: ({"high": 0, "medium": 1, "low": 2}[kv[0][0]], -kv[1]))], ["severity", "category", "n"]))
    L.append(_table(an["defects"], ["severity", "category", "sheet", "a1", "detail", "formula"]))
    L += ["## 8. Questions for the model owner", ""]
    L += [f"{i+1}. {q}" for i, q in enumerate(_questions(an))]
    L.append("")
    return "\n".join(L)


def write_gem_context(wb: dict, an: dict, include_values: bool = False, max_rows: int = 8) -> str:
    """Compact, structure-only context for an LLM. No data rows unless include_values."""
    L = [f"# STRUCTURED CONTEXT — {wb['properties']['title']}", "",
         "This is a deterministic extraction of a spreadsheet's structure. Formulas are shown as patterns (R1C1 = relative notation: R[-1]C means 'one row up, same column').", ""]
    L.append("## Sheets")
    for s in an["sheet_summary"]:
        L.append(f"- {s['sheet']} (index {s['index']}, role {s['role']}{', HIDDEN' if s['hidden'] else ''}): {s['n_cells']} cells, {s['n_formulas']} formulas, inputs {s['n_inputs']}, outputs {s['n_outputs']}; reads from [{', '.join(s['depends_on'])}]; feeds [{', '.join(s['feeds'])}]")
    L += ["", "## Calculation order (sources first)", " → ".join(an["graph"]["order_sources_first"]), ""]
    L.append("## Sheet-to-sheet references (consumer ← source: count)")
    for e in sorted(an["sheet_edges"], key=lambda e: -e["n_refs"]):
        if e["from_sheet"] != e["to_sheet"]:
            L.append(f"- {e['from_sheet']} ← {e['to_sheet']}: {e['n_refs']}")
    L += ["", "## Named ranges"] + [f"- {n['name']} = {n['sheet']}!{n['range']}" for n in wb["named_ranges"]]
    L += ["", "## Formula blocks (sheet, range, cell count, R1C1 pattern, example A1 formula)"]
    by_a1 = {(f["sheet"], f["a1"]): f for f in an["formulas"]}
    covered = set()
    for p in an["patterns"]:
        if not p["is_pattern"]:
            continue
        f = by_a1.get((p["sheet"], p["range"].split(":")[0]))
        L.append(f"- {p['sheet']}!{p['range']} ×{p['n_cells']}{' (' + str(p['n_variants']-1) + ' deviating cells)' if p['n_variants']>1 else ''}: {p['signature']}   e.g. {f['a1'] if f else ''}: {f['formula'] if f else ''}")
        covered.add((p["sheet"], p["signature"]))
    singles = [f for f in an["formulas"] if (f["sheet"], f["r1c1"]) not in covered]
    if singles:
        L += ["", "## Single formulas (not part of a block)"]
        for f in singles[:400]:
            L.append(f"- {f['sheet']}!{f['a1']}: {f['formula']}")
    # labels: row/column headers help the model name things
    L += ["", "## Labels (text cells in the first 3 columns / first 3 rows of each sheet)"]
    for s in wb["sheets"]:
        labs = [f"{c['a1']}={str(c['value'])[:40]}" for c in s["cells"] if c["kind"] == "string" and (c["col"] <= 3 or c["row"] <= 3)][:60]
        if labs:
            L.append(f"- {s['title']}: " + "; ".join(labs))
    if include_values:
        L += ["", f"## Sample values (first {max_rows} rows per sheet)"]
        for s in wb["sheets"]:
            rows = defaultdict(dict)
            for c in s["cells"]:
                if c["row"] <= max_rows:
                    rows[c["row"]][c["a1"]] = c["value"]
            for r in sorted(rows):
                L.append(f"- {s['title']} r{r}: " + ", ".join(f"{k}={v}" for k, v in rows[r].items()))
    L += ["", "## Findings"]
    for d in an["defects"]:
        L.append(f"- [{d['severity']}] {d['category']} @ {d['sheet'] or ''}!{d['a1'] or ''}: {d['detail']}" + (f" — `{d['formula']}`" if d["formula"] else ""))
    L += ["", "## Functions used", ", ".join(f"{k}({v})" for k, v in an["functions"].items())]
    return "\n".join(L) + "\n"
