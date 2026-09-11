# sheets_decomposer

Deterministic structural extraction of a spreadsheet (Google Sheets or .xlsx) into JSON + DuckDB + a Markdown report + a compact LLM context. Built to practice the approach described to Included Health: **scripts do the extraction and the deterministic checks; the model only sees structured output; a human reviews anything that becomes a source of truth.**

```
Google Sheets URL ──(Sheets API, one call)──┐
.xlsx file ────────(openpyxl)───────────────┼─► unified workbook dict ─► analyze ─► out/<name>/
link-shared URL ───(xlsx export, no auth)───┘                                        ├─ model.json      full extraction + analysis
                                                                                     ├─ model.duckdb    18 tables + views, query it
                                                                                     ├─ report.md       inventory, flow diagram, patterns, findings, questions
                                                                                     └─ gem_context.md  structure-only context for Gemini/Claude (no data rows by default)
```

## Setup

```bash
source ~/anaconda3/etc/profile.d/conda.sh && conda activate sheets   # env already created
cd ~/code/sheets_decomposer
./sd --help
```
Google credentials: see `SETUP_GOOGLE_API.md`. Not needed for `.xlsx` or link-shared sheets.

## Use

```bash
./sd sample                                       # seeded practice workbook + defect key in out/
./sd ingest out/sample_calls_chats.xlsx           # ingest a file
./sd ingest "https://docs.google.com/spreadsheets/d/<ID>/edit"                 # OAuth (default)
./sd ingest "https://docs.google.com/spreadsheets/d/<ID>/edit" --auth export   # link-shared, no creds
./sd ingest <src> --include-values                # add sample rows to gem_context.md (practice data only)
./sd query out/<name>/model.duckdb "select * from vw_defects"
./sd query out/<name>/model.duckdb -f sql/practice_queries.sql
./sd tables out/<name>/model.duckdb
```

## What the analyzer derives

| Output | Meaning |
|---|---|
| `sheet_summary` | per-sheet role (`input/raw`, `config`, `calc`, `output`, `orphan`), formula ratio, what it reads and what reads it |
| `edges` / `sheet_edges` | every reference a formula makes; aggregated to a sheet dependency graph (mermaid in the report) |
| `patterns` | contiguous runs of formulas collapsed to one R1C1 signature; `n_variants > 1` = a run that breaks its own pattern |
| `cell_roles` | `input` (literal that formulas read), `calc`, `output` (formula nothing reads), `static`, `label` |
| `defects` | high/medium/low findings: `hardcoded_in_formula_range`, `inconsistent_formula`, `magic_number`, `broken_reference`, `error_value`, `text_number`, `external_dependency`, `dynamic_reference`, `volatile_function`, `hidden_sheet`, `orphan_sheet`, `circular_reference`, `missing_checks`, `unused_named_range`, `whole_column_reference`, `complex_formula` |

What it cannot see: staleness (a date typed in a cell), semantic wrongness (a formula that is consistent but computes the wrong thing), and business intent behind an override. Those are the human's job and the report's "Questions for the model owner" section is where they start.

## The method this supports (six steps)

1. Confirm the question before touching a cell.
2. Inventory: what is here, where data enters, what depends on what.  ← `report.md` §1–2
3. Read the logic as patterns, not cells.  ← §3, `vw_formula_patterns`
4. List defects in the owner's vocabulary; severity and location.  ← §7, `vw_defects`
5. Build alongside, never modify in place; reconcile the two.
6. Write it up: assumptions, findings, changes, checks, limits, next.  ← `TakeHome_WriteUp_Template.md` in the vault
