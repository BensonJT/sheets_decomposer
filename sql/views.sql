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

-- ---------------------------------------------------------------------------
-- Self-description. Query vw_schema instead of dumping the catalog; it carries
-- table/column comments so a human or an AI assistant can orient without the docs.
-- ---------------------------------------------------------------------------
COMMENT ON TABLE workbook IS 'One row: source type/id/url, fetch time, sheet count, Drive metadata (json)';
COMMENT ON TABLE sheets IS 'One row per tab: hidden flag, grid size, frozen panes, tab color';
COMMENT ON TABLE cells IS 'Every populated cell. kind = formula|number|string|bool|date|error. value is the evaluated result as text (null for xlsx written by a script)';
COMMENT ON COLUMN cells.kind IS 'What the user entered: formula|number|string|bool|date|error|empty';
COMMENT ON COLUMN cells.value IS 'Evaluated result as text; error cells hold the error token (#REF!, #N/A ...)';
COMMENT ON TABLE formulas IS 'One row per formula cell with the parsed detail: R1C1 signature, functions, ref count, flags';
COMMENT ON COLUMN formulas.r1c1 IS 'Formula rewritten with references relative to its own cell; identical r1c1 across a run = one pattern block';
COMMENT ON COLUMN formulas.functions IS 'JSON list of function names used';
COMMENT ON COLUMN formulas.magic_numbers IS 'JSON list of numeric literals in the formula other than 0/1/2/100';
COMMENT ON COLUMN formulas.has_dynamic IS 'Uses INDIRECT/OFFSET: dependencies cannot be traced statically';
COMMENT ON COLUMN formulas.has_external IS 'Uses IMPORTRANGE or another IMPORT* function';
COMMENT ON TABLE edges IS 'One row per reference a formula makes: from (sheet,a1) to (sheet,range). kind = cell|range|cols|rows|named|external';
COMMENT ON COLUMN edges.cells IS 'Number of cells in the referenced range; null for open-ended (A:A) references';
COMMENT ON TABLE sheet_edges IS 'edges aggregated to sheet -> sheet with reference counts (from_sheet depends on to_sheet)';
COMMENT ON TABLE cell_roles IS 'Every cell classified: input (literal that formulas read), calc, output (formula nothing reads), static, label';
COMMENT ON TABLE sheet_summary IS 'Per-sheet counts, formula ratio, role (input/raw|config|calc|output|orphan), depends_on and feeds lists';
COMMENT ON TABLE patterns IS 'Contiguous runs of formulas with the same R1C1 signature. is_pattern = true when >=3 cells and >=60% agree';
COMMENT ON COLUMN patterns.axis IS 'col = run goes down a column; row = run goes across a row';
COMMENT ON COLUMN patterns.n_variants IS 'Distinct signatures in the run; >1 on a pattern means a cell breaks it';
COMMENT ON TABLE defects IS 'Findings with severity high|medium|low and a category; see vw_defect_counts';
COMMENT ON COLUMN defects.category IS 'hardcoded_in_formula_range, inconsistent_formula, magic_number, broken_reference, error_value, text_number, external_dependency, dynamic_reference, volatile_function, hidden_sheet, hidden_rows_cols, orphan_sheet, circular_reference, missing_checks, unused_named_range, whole_column_reference, complex_formula';
COMMENT ON TABLE named_ranges IS 'Defined names with their sheet and A1 range';
COMMENT ON TABLE validations IS 'Data-validation rules per cell/range (values is json)';
COMMENT ON TABLE protected_ranges IS 'Protected ranges or sheet-level protection';
COMMENT ON TABLE conditional_formats IS 'Conditional format rules (ranges and values are json)';
COMMENT ON TABLE charts IS 'Charts with their source ranges (Sheets API path only)';
COMMENT ON TABLE merges IS 'Merged cell ranges';
COMMENT ON TABLE functions IS 'Function usage counts across the workbook';
COMMENT ON TABLE importranges IS 'IMPORTRANGE targets: source spreadsheet id and range';

CREATE OR REPLACE VIEW vw_schema AS
SELECT
    c.schema_name                                   AS table_schema,
    c.table_name,
    CASE WHEN t.internal THEN 'internal' WHEN v.view_name IS NOT NULL THEN 'view' ELSE 'table' END AS object_type,
    c.column_name,
    c.column_index                                  AS ordinal_position,
    c.data_type,
    c.character_maximum_length,
    c.numeric_precision,
    c.numeric_scale,
    CASE WHEN c.is_nullable THEN 'YES' ELSE 'NO' END AS is_nullable,
    c.column_default,
    con.constraint_type,
    coalesce(c.comment, '')                         AS column_description,
    coalesce(tc.comment, vc.comment, '')            AS table_description,
    CASE
        WHEN c.data_type IN ('INTEGER','BIGINT','SMALLINT','TINYINT','HUGEINT','UINTEGER','UBIGINT','DOUBLE','FLOAT','DECIMAL') OR c.data_type LIKE 'DECIMAL%' THEN 'numeric'
        WHEN c.data_type IN ('VARCHAR','CHAR','TEXT','STRING') THEN 'text'
        WHEN c.data_type IN ('DATE','TIME','TIMESTAMP','TIMESTAMP WITH TIME ZONE','INTERVAL') THEN 'temporal'
        WHEN c.data_type = 'BOOLEAN' THEN 'boolean'
        WHEN c.data_type = 'JSON' THEN 'json'
        WHEN c.data_type LIKE '%[]' OR c.data_type LIKE 'LIST%' THEN 'array'
        WHEN c.data_type = 'UUID' THEN 'uuid'
        ELSE 'other'
    END AS data_type_category
FROM duckdb_columns() c
LEFT JOIN duckdb_tables() t  ON t.schema_name = c.schema_name AND t.table_name = c.table_name
LEFT JOIN duckdb_views()  v  ON v.schema_name = c.schema_name AND v.view_name  = c.table_name
LEFT JOIN (SELECT schema_name, table_name, comment FROM duckdb_tables()) tc ON tc.schema_name = c.schema_name AND tc.table_name = c.table_name
LEFT JOIN (SELECT schema_name, view_name AS table_name, comment FROM duckdb_views()) vc ON vc.schema_name = c.schema_name AND vc.table_name = c.table_name
LEFT JOIN (
    SELECT schema_name, table_name, unnest(constraint_column_names) AS column_name,
           CASE constraint_type WHEN 'PRIMARY KEY' THEN 'PRIMARY KEY' WHEN 'FOREIGN KEY' THEN 'FOREIGN KEY' WHEN 'UNIQUE' THEN 'UNIQUE' ELSE constraint_type END AS constraint_type
    FROM duckdb_constraints()
) con ON con.schema_name = c.schema_name AND con.table_name = c.table_name AND con.column_name = c.column_name
WHERE c.schema_name = 'main' AND NOT c.internal
ORDER BY object_type, c.table_name, c.column_index;
