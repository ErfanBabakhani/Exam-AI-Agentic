# pdf_them - Zanista Gradient PDF Export Theme

A backend-ready ReportLab theme for polished grading-result PDF exports.

## Install dependency

```bash
pip install reportlab
```

## Usage

Place this folder under:

```text
backend/pdf_them
```

Then call:

```python
from pdf_them.renderer import render_grading_report_pdf
render_grading_report_pdf(report_data, "/tmp/grading_report.pdf")
```

## Design direction

`G - Zanista Gradient`: modern SaaS / AI-product style with a gradient cover, score donut, summary metrics, run cards, question cards, evidence chips, and clean rubric sections.

## Notes

- No sample-specific hardcoding.
- No copyrighted template assets.
- No font files included.
- Uses system fonts when available, otherwise falls back to Helvetica.
