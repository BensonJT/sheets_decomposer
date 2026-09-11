-- Practice queries. Run one at a time:  sd query out/<slug>/model.duckdb -f sql/practice_queries.sql  (runs all)
-- 1. What is in this workbook?
SELECT * FROM vw_sheet_summary;
-- 2. What depends on what?
SELECT * FROM vw_sheet_dependency;
-- 3. Where does the data enter? (literal cells that formulas consume)
SELECT sheet, count(*) AS n_inputs FROM vw_inputs GROUP BY 1 ORDER BY 2 DESC;
-- 4. What are the terminal outputs?
SELECT sheet, count(*) AS n_outputs FROM vw_outputs GROUP BY 1 ORDER BY 2 DESC;
-- 5. Defect list, high severity first
SELECT * FROM vw_defect_counts;
-- 6. Which columns break their own pattern?
SELECT * FROM vw_inconsistent_patterns;
-- 7. Every distinct formula logic in the workbook (one row per pattern, not per cell)
SELECT sheet, axis, range, n_cells, signature FROM vw_formula_patterns ORDER BY sheet, range;
-- 8. Which cells does one cell feed? (change target)
SELECT DISTINCT from_sheet, from_a1 FROM edges WHERE to_sheet='Assumptions' AND to_range LIKE 'B%' ORDER BY 1,2;
-- 9. External spreadsheets this model depends on
SELECT * FROM vw_external_refs;
-- 10. Function vocabulary (tells you the author's skill level and the model's style)
SELECT * FROM vw_functions;
