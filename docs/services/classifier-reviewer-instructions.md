# Review the V4 label sheet

**For future genuine human review only.** The owner confirmed on 22 Nov 2026
that all existing classifier label datasets, including round 1 once called
human gold, are AI-generated (roadmap D16). Preserve those historical sheets;
these instructions do not turn them into human labels. Human validation and
the 200 human labels/class target remain **not met**.

## Purpose

This sheet collects human topic labels for fresh articles so the V4 classifier can be evaluated and, later, trained on reviewed examples. The rows are candidates, not confirmed labels or training data. Label the article yourself; do not try to make the class counts look balanced.

## What to do

1. Read the article's `title` and `summary`.
2. Choose exactly one topic using the [V4 taxonomy guide](../../data/labels/labelling-guide.md). Enter its exact `id` in `label`. Use `unsorted` if no topic fits or the text does not support a confident choice.
3. Use `notes` only to explain an uncertain or unusual decision, such as why you chose one topic over another. Keep notes brief.
4. Save the reviewed CSV in its original run directory, as CSV with UTF-8 encoding.

Make the judgement yourself. Do not copy an AI-agent or model prediction into
the sheet and record it as human work.

## Do not change

- `article_id`, `title`, or `summary`; use only the title and summary to decide the label. Do not search for the full article or use outside information.
- The column names or order, row order, or number of rows. Do not add, delete, sort, or duplicate rows, or add columns.
- The CSV filename or its run directory. Keep this sheet separate from the other review sheets.
- The taxonomy or label spelling. Do not invent labels or copy provisional/model suggestions into `label`.

Keep the sheet and its article text within the approved private review process. Do not commit it to Git or share it publicly. Only genuinely human-authored labels can become human gold after the project verification and import steps. Those checks establish text consistency and agreement, not authorship; a `gold.jsonl` filename is not proof. The full workflow is in the [V4 README](classifier.md).
