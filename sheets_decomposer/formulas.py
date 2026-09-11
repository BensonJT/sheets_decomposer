"""Formula tokenizer: references, functions, literals, R1C1 signatures.

Regex-based, deliberately simple. Good enough for Sheets/Excel formulas as
written by analysts; not a full grammar. Everything here is deterministic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

# ---------------------------------------------------------------- A1 helpers
def col_to_idx(col: str) -> int:
    """'A' -> 1, 'Z' -> 26, 'AA' -> 27."""
    n = 0
    for ch in col.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def idx_to_col(idx: int) -> str:
    s = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        s = chr(65 + rem) + s
    return s


def a1(row: int, col: int) -> str:
    return f"{idx_to_col(col)}{row}"


# ------------------------------------------------------------------ patterns
_COL = r"\$?[A-Z]{1,3}"
_ROW = r"\$?[0-9]{1,7}"
_CELL = rf"{_COL}{_ROW}"
_RANGE_BODY = rf"(?:{_CELL}(?::{_CELL})?|{_COL}:{_COL}|{_ROW}:{_ROW})"
_SHEET = r"(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_\.]*)"

QUAL_REF = re.compile(rf"(?P<sheet>{_SHEET})!(?P<rng>{_RANGE_BODY})")
BARE_REF = re.compile(rf"(?<![A-Za-z0-9_\.!\$])(?P<rng>{_RANGE_BODY})(?![A-Za-z0-9_\(])")
FUNC = re.compile(r"(?<![A-Za-z0-9_\.])([A-Za-z_][A-Za-z0-9_\.]*)\s*\(")
IDENT = re.compile(r"(?<![A-Za-z0-9_\.!'\"])([A-Za-z_][A-Za-z0-9_\.]{1,})(?![A-Za-z0-9_\(!])")
NUMBER = re.compile(r"(?<![A-Za-z0-9_\.\[«])(\d+\.?\d*(?:[eE][+-]?\d+)?)(?![A-Za-z0-9_\]»])")
STRING = re.compile(r'"(?:[^"]|"")*"')
ERROR = re.compile(r"#(?:REF!|N/A|DIV/0!|VALUE!|NAME\?|NUM!|NULL!|ERROR!)")
IMPORTRANGE = re.compile(r"IMPORTRANGE\s*\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)", re.I)
SHEET_ID_IN_URL = re.compile(r"/d/([A-Za-z0-9_-]{20,})")

VOLATILE = {"NOW", "TODAY", "RAND", "RANDBETWEEN", "RANDARRAY", "OFFSET", "INDIRECT"}
DYNAMIC = {"INDIRECT", "OFFSET"}
EXTERNAL = {"IMPORTRANGE", "IMPORTDATA", "IMPORTHTML", "IMPORTXML", "IMPORTFEED", "GOOGLEFINANCE"}
LOOKUP = {"VLOOKUP", "HLOOKUP", "XLOOKUP", "INDEX", "MATCH", "LOOKUP", "FILTER", "QUERY", "SUMIF", "SUMIFS", "COUNTIF", "COUNTIFS", "AVERAGEIF", "AVERAGEIFS", "MAXIFS", "MINIFS"}
ERROR_HANDLING = {"IFERROR", "IFNA", "ISERROR", "ISERR", "ISNA", "ERROR.TYPE"}
# literals considered "structural", never flagged as magic numbers
BENIGN_LITERALS = {"0", "1", "2", "100", "-1", "0.0", "1.0"}


@dataclass
class Ref:
    raw: str
    sheet: str | None          # None = same sheet
    rng: str                   # A1 body without sheet
    kind: str                  # cell | range | cols | rows
    start_row: int | None = None
    start_col: int | None = None
    end_row: int | None = None
    end_col: int | None = None
    abs_flags: str = ""        # e.g. "$C$R" for fully absolute

    def cell_count(self) -> int | None:
        if self.kind == "cell":
            return 1
        if self.kind == "range":
            return (self.end_row - self.start_row + 1) * (self.end_col - self.start_col + 1)
        return None  # open-ended


@dataclass
class ParsedFormula:
    formula: str
    r1c1: str
    functions: list[str] = field(default_factory=list)
    refs: list[Ref] = field(default_factory=list)
    named_candidates: list[str] = field(default_factory=list)
    literals: list[str] = field(default_factory=list)
    magic_numbers: list[str] = field(default_factory=list)
    strings: list[str] = field(default_factory=list)
    importranges: list[dict] = field(default_factory=list)
    errors_in_text: list[str] = field(default_factory=list)
    nesting_depth: int = 0
    length: int = 0
    has_external: bool = False
    has_dynamic: bool = False
    has_volatile: bool = False
    has_error_handling: bool = False
    has_whole_column_ref: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["refs"] = [asdict(r) for r in self.refs]
        return d


def _unquote_sheet(s: str) -> str:
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1].replace("''", "'")
    return s


def _split_cell(cell: str) -> tuple[bool, int, bool, int]:
    m = re.fullmatch(r"(\$?)([A-Z]{1,3})(\$?)(\d+)", cell)
    return bool(m.group(1)), col_to_idx(m.group(2)), bool(m.group(3)), int(m.group(4))


def parse_ref(raw: str, sheet: str | None) -> Ref:
    body = raw
    if ":" in body:
        a, b = body.split(":", 1)
        if re.fullmatch(_CELL, a) and re.fullmatch(_CELL, b):
            _, c1, _, r1 = _split_cell(a)
            _, c2, _, r2 = _split_cell(b)
            return Ref(raw, sheet, body, "range", min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))
        if re.fullmatch(_COL, a):
            c1, c2 = col_to_idx(a.strip("$")), col_to_idx(b.strip("$"))
            return Ref(raw, sheet, body, "cols", None, min(c1, c2), None, max(c1, c2))
        r1, r2 = int(a.strip("$")), int(b.strip("$"))
        return Ref(raw, sheet, body, "rows", min(r1, r2), None, max(r1, r2), None)
    ac, c, ar, r = _split_cell(body)
    return Ref(raw, sheet, body, "cell", r, c, r, c, abs_flags=("$C" if ac else "") + ("$R" if ar else ""))


def _r1c1_part(part: str, row: int, col: int) -> str:
    """Convert one A1 fragment ('$A$1', 'B', '3') to R1C1 relative to (row, col)."""
    m = re.fullmatch(r"(\$?)([A-Z]{1,3})(\$?)(\d+)", part)
    if m:
        ac, c, ar, r = bool(m.group(1)), col_to_idx(m.group(2)), bool(m.group(3)), int(m.group(4))
        rs = f"R{r}" if ar else ("R" if r == row else f"R[{r - row}]")
        cs = f"C{c}" if ac else ("C" if c == col else f"C[{c - col}]")
        return rs + cs
    m = re.fullmatch(r"(\$?)([A-Z]{1,3})", part)
    if m:
        c = col_to_idx(m.group(2))
        return f"C{c}" if m.group(1) else ("C" if c == col else f"C[{c - col}]")
    m = re.fullmatch(r"(\$?)(\d+)", part)
    if m:
        r = int(m.group(2))
        return f"R{r}" if m.group(1) else ("R" if r == row else f"R[{r - row}]")
    return part


def to_r1c1(rng: str, row: int, col: int) -> str:
    return ":".join(_r1c1_part(p, row, col) for p in rng.split(":"))


def parse_formula(formula: str, row: int, col: int, known_names: set[str] | None = None) -> ParsedFormula:
    text = formula[1:] if formula.startswith("=") else formula
    pf = ParsedFormula(formula=formula, r1c1="", length=len(text))

    # 1. strings out
    strings: list[str] = []
    def _s(m):
        strings.append(m.group(0))
        return f'"§{len(strings) - 1}"'
    work = STRING.sub(_s, text)
    pf.strings = [s[1:-1] for s in strings]

    # 2. errors embedded in the formula text itself (#REF! after a deleted row)
    pf.errors_in_text = ERROR.findall(work)

    # 3. functions
    pf.functions = sorted({m.group(1).upper() for m in FUNC.finditer(work)})
    fset = set(pf.functions)
    pf.has_volatile = bool(fset & VOLATILE)
    pf.has_dynamic = bool(fset & DYNAMIC)
    pf.has_external = bool(fset & EXTERNAL)
    pf.has_error_handling = bool(fset & ERROR_HANDLING)

    # 4. IMPORTRANGE targets
    for m in IMPORTRANGE.finditer(work):
        def _resolve(tok: str) -> str:
            tok = tok.strip()
            sm = re.fullmatch(r'"§(\d+)"', tok)
            return strings[int(sm.group(1))][1:-1] if sm else f"<dynamic:{tok}>"
        src, rng = _resolve(m.group(1)), _resolve(m.group(2))
        idm = SHEET_ID_IN_URL.search(src)
        pf.importranges.append({"source": src, "spreadsheet_id": idm.group(1) if idm else (src if not src.startswith("<") else None), "range": rng})

    # 5. references — qualified first, then bare; build R1C1 alongside
    refs: list[Ref] = []
    r1c1 = work
    def _q(m):
        sheet = _unquote_sheet(m.group("sheet"))
        refs.append(parse_ref(m.group("rng"), sheet))
        return f"«{len(refs) - 1}»"
    r1c1 = QUAL_REF.sub(_q, r1c1)
    def _b(m):
        refs.append(parse_ref(m.group("rng"), None))
        return f"«{len(refs) - 1}»"
    r1c1 = BARE_REF.sub(_b, r1c1)
    pf.refs = refs
    pf.has_whole_column_ref = any(r.kind in ("cols", "rows") for r in refs)

    stripped = r1c1  # refs replaced by «n» — use for literals & names
    for i, r in enumerate(refs):
        q = f"'{r.sheet}'!" if r.sheet and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_\.]*", r.sheet) else (f"{r.sheet}!" if r.sheet else "")
        r1c1 = r1c1.replace(f"«{i}»", q + to_r1c1(r.rng, row, col), 1)
    for i, st in enumerate(strings):  # restore string literals in the signature
        r1c1 = r1c1.replace(f'"§{i}"', st, 1)
    pf.r1c1 = "=" + r1c1

    # 6. named-range candidates: identifiers that are not functions
    cands = []
    for m in IDENT.finditer(stripped):
        tok = m.group(1)
        if tok.upper() in fset or tok.upper() in ("TRUE", "FALSE") or tok.startswith("§"):
            continue
        if known_names is not None and tok not in known_names:
            continue
        cands.append(tok)
    pf.named_candidates = sorted(set(cands))

    # 7. numeric literals
    lits = NUMBER.findall(stripped)
    pf.literals = lits
    pf.magic_numbers = [x for x in lits if x not in BENIGN_LITERALS]

    # 8. nesting depth
    depth = mx = 0
    for ch in work:
        if ch == "(":
            depth += 1
            mx = max(mx, depth)
        elif ch == ")":
            depth -= 1
    pf.nesting_depth = mx
    return pf


if __name__ == "__main__":  # smoke test
    tests = [
        ("=SUM(A1:A10)*Assumptions!$B$2", 12, 3),
        ("=IFERROR(VLOOKUP(B5,'Raw Paste'!A:C,3,FALSE),0)", 5, 4),
        ("=IMPORTRANGE(\"https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit\",\"Forecast!A1:M20\")", 1, 1),
        ("=C4*1.05/(1-Shrinkage)", 4, 5),
        ("=INDIRECT(\"Staffing_Calc!\"&B2)", 2, 3),
        ("=LOG10(D4)+#REF!", 4, 5),
    ]
    for f, r, c in tests:
        p = parse_formula(f, r, c, known_names={"Shrinkage"})
        print(f, "\n  ->", p.r1c1, p.functions, [x.raw for x in p.refs], p.named_candidates, p.magic_numbers, p.importranges, p.errors_in_text)
