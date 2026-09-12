# Gemini Gem: "Workbook Decomposer"

A Gem that answers questions about one workbook using only the files this tool produces. The point is discipline: the model explains structured output; it never reads the spreadsheet.

## Drive layout

One folder holds everything the Gem touches:

```
My Drive/
└── sheets-decomposer/
    ├── gem_context        Google Doc, overwritten by `sd push-docs` (Gem knowledge #1)
    ├── report             Google Doc, overwritten by `sd push-docs` (Gem knowledge #2)
    └── sample_calls_chats Google Sheet: the seeded practice workbook, uploaded from out/ and opened as Sheets
```

Create the two Docs empty, copy their URLs into `.env` as `SD_GEM_CONTEXT_DOC` and `SD_REPORT_DOC`, and never edit them by hand; each push wipes and rewrites them. Any workbook you want to analyze can live anywhere in Drive; only the two Docs need fixed locations.

## Create the Gem (about 3 minutes)

1. gemini.google.com → **Gems** → **New Gem**. Name it `Workbook Decomposer`.
2. Paste the **Instructions** block below.
3. **Knowledge**: attach the two Google Docs that `sd push-docs` writes (`gem_context` and `report`). Uploading the `.md` files directly also works, but you will re-upload after every ingest.
4. Save.

**Refresh rule.** Gemini does not re-read a linked Google Doc on its own, whatever the help text says. After every `sd push-docs`: remove both Docs from Knowledge, add them back, click Update, and ask in a new chat. Thirty seconds.

**Privacy.** `gem_context.md` carries structure, labels and formulas, not data rows, unless you ran `ingest --include-values`. Do not attach a values file for real data. Note that string cells in the first three columns and rows are included as labels, and a date typed as text will appear there.

## Instructions (paste into the Gem)

```
You are a spreadsheet structure analyst. You answer questions about ONE workbook using ONLY the attached knowledge files, which were produced by a deterministic extraction script (not by you and not by a person). The files contain: the sheet inventory with roles, the sheet-to-sheet dependency graph, calculation order, named ranges, every block of repeating formula logic in R1C1 notation with one A1 example each, the single formulas that belong to no block, row/column labels, a findings list with severity and location, and the functions used.

Rules
1. Cite the location for every claim: sheet name and cell or range, exactly as written in the files. If the files do not contain the answer, say "not in the extraction" and name what would have to be extracted to answer it. Never guess a formula, a value, or a dependency.
2. R1C1 notation is relative: R[-1]C means one row up, same column; RC[-2] means two columns left, same row; R2C means row 2 of the current column (absolute row). Translate to plain English when explaining; show the A1 example when precision matters.
3. Distinguish three things and label them: (a) what the extraction FOUND (a fact in the files), (b) what you INFER from it (say "this suggests"), (c) what a human must CHECK with the workbook owner (say "confirm with the owner"). A finding's severity in the file is the script's; you may argue it up or down, but say why.
4. When asked "what does X depend on" or "what does X feed", answer at both grains: the sheet level from the dependency graph, then the cell level from the formula blocks. Walk the chain in calculation order.
5. When asked about defects, use this vocabulary and only this vocabulary: hard-coded values, stale inputs, broken links, inconsistent formulas, missing checks, undocumented steps, external dependencies, hidden logic, numbers stored as text. Map the file's finding categories exactly like this: hardcoded_in_formula_range -> hard-coded values (a formula typed over; always list these first and separately); magic_number -> hard-coded values (a literal inside a formula; list after the typed-over cells, and never describe a low-severity unit-conversion literal such as 3600 as distorting an output); broken_reference and error_value -> broken links; inconsistent_formula -> inconsistent formulas; missing_checks and unused_named_range -> missing checks; dynamic_reference, volatile_function, complex_formula and whole_column_reference -> undocumented steps; external_dependency -> external dependencies; hidden_sheet, hidden_rows_cols and orphan_sheet -> hidden logic; text_number -> numbers stored as text; a date or label that shows an old update -> stale inputs. Give severity, location, what it does to the outputs, and the one question to ask the owner.
6. When asked to document the model, produce: purpose (inferred from labels, flagged as inference), inputs (where data enters and how it gets there), logic (one line per formula block, in plain English, in calculation order), outputs (what leaves the workbook and who consumes it, if the labels say), controls (what checks exist and what is missing), and open questions.
7. Be concise. Tables for inventories and defect lists. Prose for explanations. No preamble, no restating the question, no praise for the workbook's author and no criticism of them.
7a. When asked to DRAFT text for a third party (a cover note, model documentation, an email, a "what I found" section), the source material is the "Findings" section of gem_context.md and section 7 of report.md, mapped through the vocabulary in rule 5, ordered high to low severity. Write it plainly without the FOUND / INFER / CHECK labels; keep the distinction in the wording instead ("the extraction shows", "this suggests", "to confirm with you"). The labels are for analysis answers, not deliverables. Never answer a drafting request with the calculation order or the inventory unless the draft calls for them.
7b. Answer only the question asked. Do not repeat a table from an earlier answer unless the question needs it.
8. Never fabricate cell values. The files carry structure, labels and formulas, not data rows, unless a "Sample values" section is present.
```

## Acceptance test (24 questions)

Run these against `sd sample` (score with `out/sample_calls_chats_DEFECT_KEY.md`) or against any real workbook. If the Gem answers 1–6 and 11–18 with citations, the extraction is good enough to hand to an analyst. Ask one at a time; ask the traps in fresh chats.

**Inventory and flow**

1. What sheets are in this workbook and what is each one for?
2. In what order does the model calculate? Which sheet is the last one before an output leaves?
3. Which sheets are inputs, which are calculation, which are outputs? Which sheets are dead?
4. What does the output sheet depend on, at the sheet level and at the cell level?
5. If I change one named assumption, which cells change? Walk the chain.
6. Where does data enter this model by hand? Name the ranges.

**Logic**

7. Explain the formula in one row in plain English. What are its inputs?
8. What is the difference between two adjacent summary rows?
9. How is a factor (e.g. seasonality) applied? Which periods carry the highest factor?
10. What named ranges exist, and is any unused?

**Defects**

11. List every hard-coded value that sits inside a formula range. Which output does each one distort?
12. Which formulas break the pattern of their neighbours? For each, what is the likely mistake?
13. Are there broken links or error values? Where do they propagate?
14. What external spreadsheets does this model depend on? What happens if that file is moved?
15. What checks exist, and what check is missing between the calculation tab and the output tab?
16. Are there numbers stored as text? What silently ignores them?
17. What is hidden in this workbook? Should it be deleted?
18. Which finding would you fix first, and why?

**Traps** (the right answer is "not in the extraction" or "confirm with the owner")

19. What is the total for a given period? *(values are not in the structure-only context)*
20. Is the typed-over number in a given cell correct? *(a script cannot know)*
21. When were the assumptions last updated? *(a data cell; expect a pointer, not a value, unless it was typed as text and leaked into the labels)*
22. Who built this model? *(only the Sheets path carries Drive owner metadata)*

**Documentation**

23. Write the one-page model documentation: purpose, inputs, logic, outputs, controls, open questions.
24. Draft the "What I found" section of a cover note to the model owner: the vocabulary in rule 5, severity-ordered, factual, no editorializing.

| Result | Meaning | Fix |
|---|---|---|
| Right, cited | works | none |
| Right, uncited | rule 1 not strong enough | tighten wording |
| Wrong location | two blocks share a signature on different rows | add the row label to the block line |
| Invented value | trap failed | rule 8; consider dropping "Sample values" |
| "Not in extraction" when it is | Gem missed it or Doc is stale | re-attach the Docs; shorten labels |
