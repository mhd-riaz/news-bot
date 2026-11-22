# Review the V4 label sheet

## Purpose

This sheet collects human topic labels for fresh articles so the V4 classifier can be evaluated and, later, trained on reviewed examples. The rows are candidates, not confirmed labels or training data. Label the article yourself; do not try to make the class counts look balanced.

## What to do

1. Read the article's `title` and `summary`.
2. Choose exactly one topic using the [V4 taxonomy guide](../ml/data/labels/v4/labelling-guide.md). Enter its exact `id` in `label`. Use `unsorted` if no topic fits or the text does not support a confident choice.
3. Use `notes` only to explain an uncertain or unusual decision, such as why you chose one topic over another. Keep notes brief.
4. Save the reviewed CSV in its original run directory, as CSV with UTF-8 encoding.

## Do not change

- `article_id`, `title`, or `summary`; use only the title and summary to decide the label. Do not search for the full article or use outside information.
- The column names or order, row order, or number of rows. Do not add, delete, sort, or duplicate rows, or add columns.
- The CSV filename or its run directory. Keep this sheet separate from the other review sheets.
- The taxonomy or label spelling. Do not invent labels or copy provisional/model suggestions into `label`.

Keep the sheet and its article text within the approved private review process. Do not commit it to Git or share it publicly. Labels become gold data only after the project verification and import steps; the full workflow is in the [V4 README](README.md).
