"""CLI:  sd ingest <url|id|path.xlsx>  |  sd sample  |  sd query <db> "<sql>"  |  sd gem-context <out_dir>"""
from __future__ import annotations

import json
import re
from pathlib import Path

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False, help=__doc__)
console = Console()
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"


def _slug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s[:60] or "workbook"


@app.command()
def ingest(
    source: str = typer.Argument(..., help="Google Sheets URL / spreadsheet ID, or a local .xlsx path"),
    name: str = typer.Option(None, "--name", "-n", help="Output folder name under out/ (default: workbook title)"),
    auth: str = typer.Option("oauth", "--auth", "-a", help="oauth | service | export (no auth; link-shared only)"),
    include_values: bool = typer.Option(False, "--include-values", help="Put sample data rows into gem_context.md (default: structure only)"),
    out_dir: Path = typer.Option(OUT, "--out", help="Base output directory"),
):
    """Fetch a workbook, analyze it, write model.json + model.duckdb + report.md + gem_context.md."""
    from . import analyze as _an, report as _rep, store as _st

    src = source.strip()
    is_file = src.lower().endswith((".xlsx", ".xlsm")) and Path(src).exists()
    with console.status("fetching…"):
        if is_file:
            from .fetch_xlsx import fetch
            wb = fetch(src)
        elif auth == "export":
            from .fetch_sheets import fetch_via_export, spreadsheet_id
            from .fetch_xlsx import fetch
            sid = spreadsheet_id(src)
            xlsx = fetch_via_export(src, out_dir / "_downloads")
            wb = fetch(xlsx, source_type="export", source_meta={"id": sid, "url": f"https://docs.google.com/spreadsheets/d/{sid}/edit"})
        else:
            from .fetch_sheets import fetch
            wb = fetch(src, auth_mode=auth)
    title = wb["properties"]["title"]
    folder = out_dir / (name or _slug(title))
    folder.mkdir(parents=True, exist_ok=True)
    with console.status("analyzing…"):
        an = _an.analyze(wb)
    (folder / "model.json").write_text(json.dumps({"workbook": wb, "analysis": an}, indent=1, default=str))
    _st.write_duckdb(str(folder / "model.duckdb"), wb, an)
    (folder / "report.md").write_text(_rep.write_report(wb, an))
    (folder / "gem_context.md").write_text(_rep.write_gem_context(wb, an, include_values=include_values))

    t = Table(title=f"{title} — {len(wb['sheets'])} sheets, {len(an['formulas'])} formulas, {len(an['defects'])} findings")
    for c in ("sheet", "role", "n_cells", "n_formulas", "depends_on", "feeds"):
        t.add_column(c)
    for s in an["sheet_summary"]:
        t.add_row(s["sheet"] + (" (hidden)" if s["hidden"] else ""), s["role"], str(s["n_cells"]), str(s["n_formulas"]), ", ".join(s["depends_on"]), ", ".join(s["feeds"]))
    console.print(t)
    from collections import Counter
    cnt = Counter((d["severity"], d["category"]) for d in an["defects"])
    for (sev, cat), n in sorted(cnt.items(), key=lambda kv: ({"high": 0, "medium": 1, "low": 2}[kv[0][0]], -kv[1])):
        rprint(f"  [{'red' if sev=='high' else 'yellow' if sev=='medium' else 'dim'}]{sev:6}[/] {cat:28} {n}")
    rprint(f"\n[green]wrote[/] {folder}/  (model.json, model.duckdb, report.md, gem_context.md)")


@app.command()
def sample(out: Path = typer.Option(OUT / "sample_calls_chats.xlsx", "--out")):
    """Write the seeded practice workbook + its defect key."""
    from .sample import build
    p, k = build(str(out))
    rprint(f"[green]wrote[/] {p}\n[green]key  [/] {k}\nNext: sd ingest {p}   (or upload to Drive, open as Sheets, and ingest the URL)")


@app.command()
def query(
    db: Path = typer.Argument(..., help="path to model.duckdb"),
    sql: str = typer.Argument(None, help="SQL to run (or use -f)"),
    file: Path = typer.Option(None, "-f", "--file", help="run every statement in a .sql file"),
    limit: int = typer.Option(50, "--limit"),
):
    """Run SQL against a model database. Try: sd query out/x/model.duckdb "select * from vw_defects" """
    from .store import query as q
    import pandas as pd
    pd.set_option("display.width", 220); pd.set_option("display.max_colwidth", 80); pd.set_option("display.max_columns", 30)
    raw = file.read_text() if file else (sql or "SELECT table_name FROM information_schema.tables ORDER BY 1")
    for s in raw.split(";"):
        comment = "\n".join(l.strip() for l in s.splitlines() if l.strip().startswith("--"))
        body = "\n".join(l for l in s.splitlines() if not l.strip().startswith("--")).strip()
        if not body:
            continue
        if comment:
            rprint(f"[dim]{comment}[/]")
        rprint(f"[cyan]{body}[/]")
        df = q(str(db), body)
        print(df.head(limit).to_string(index=False)); print(f"({len(df)} rows)\n")


@app.command("tables")
def tables(db: Path):
    """List tables and views in a model database."""
    from .store import query as q
    print(q(str(db), "SELECT table_name, table_type FROM information_schema.tables ORDER BY table_type, table_name").to_string(index=False))


if __name__ == "__main__":
    app()
