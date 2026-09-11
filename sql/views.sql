-- Views created on top of the model tables. Query with:  sd query out/<slug>/model.duckdb "select * from vw_sheet_summary"
CREATE OR REPLACE VIEW vw_sheet_summary AS
SELECT sheet, index, role, hidden, n_cells, n_formulas, n_literals, formula_ratio, n_inputs, n_outputs,
       array_to_string(depends_on, ', ') AS depends_on, array_to_string(feeds, ', ') AS feeds, n_charts, n_validations
FROM sheet_summary ORDER BY index;

CREATE OR REPLACE VIEW vw_sheet_dependency AS
SELECT from_sheet AS dependent, to_sheet AS source, n_refs FROM sheet_edges WHERE from_sheet <> to_sheet ORDER BY n_refs DESC;

CREATE OR REPLACE VIEW vw_defects AS
SELECT severity, category, sheet, a1, detail, formula FROM defects
ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, category, sheet, a1;

CREATE OR REPLACE VIEW vw_defect_counts AS
SELECT severity, category, count(*) AS n FROM defects GROUP BY 1,2
ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, n DESC;

CREATE OR REPLACE VIEW vw_formula_patterns AS
SELECT sheet, axis, range, n_cells, n_matching, n_variants, signature FROM patterns WHERE is_pattern ORDER BY sheet, axis, range;

CREATE OR REPLACE VIEW vw_inconsistent_patterns AS
SELECT * FROM vw_formula_patterns WHERE n_variants > 1;

CREATE OR REPLACE VIEW vw_functions AS
SELECT function, n FROM functions ORDER BY n DESC;

CREATE OR REPLACE VIEW vw_external_refs AS
SELECT sheet, a1, spreadsheet_id, range, source FROM importranges;

CREATE OR REPLACE VIEW vw_inputs AS  -- literal cells that formulas read: the model's true inputs
SELECT r.sheet, r.a1, c.kind, c.value FROM cell_roles r JOIN cells c USING (sheet, a1) WHERE r.role = 'input' ORDER BY r.sheet, r.row, r.col;

CREATE OR REPLACE VIEW vw_outputs AS  -- formula cells nothing else reads: terminal outputs (or dead calcs)
SELECT r.sheet, r.a1, c.formula, c.value FROM cell_roles r JOIN cells c USING (sheet, a1) WHERE r.role = 'output' ORDER BY r.sheet, r.row, r.col;

CREATE OR REPLACE VIEW vw_cell_dependencies AS  -- one row per (formula cell -> referenced range)
SELECT from_sheet, from_a1, to_sheet, to_range, kind, cells FROM edges;

CREATE OR REPLACE VIEW vw_precedents_by_sheet AS  -- what does each sheet read, and how much
SELECT from_sheet, to_sheet, count(*) AS n_refs, count(DISTINCT from_a1) AS n_formula_cells FROM edges GROUP BY 1,2 ORDER BY 1, 3 DESC;
