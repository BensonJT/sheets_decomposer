"""sheets_decomposer — deterministic structural extraction of spreadsheets.

Pipeline: fetch (Sheets API | xlsx | export URL) -> unified workbook dict ->
analyze (refs, R1C1 patterns, dependency graph, defects) -> outputs
(model.json, model.duckdb, report.md, gem_context.md).

Principle: scripts do the extraction and the deterministic checks; the LLM only
ever sees structured output. Data rows never go to a model unless explicitly
requested with --include-values.
"""
__version__ = "0.1.0"
