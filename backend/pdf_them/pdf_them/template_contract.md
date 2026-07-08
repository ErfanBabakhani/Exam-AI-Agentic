# PDF Theme Contract

Entry point:

```python
from pdf_them.renderer import render_grading_report_pdf
render_grading_report_pdf(report_data, output_path)
```

Expected `report_data` shape:

```python
{
  "title": "AI Grading Report",
  "subtitle": "Optional subtitle",
  "generated_at": "2026-05-15 14:20",
  "brand": "Zanista AI",
  "runs": [
    {
      "status": "completed",
      "student_file": "1.pdf",
      "exam_file": "Homework_3_sols.pdf",
      "score": 8.5,
      "max_score": 10,
      "duration": "83.6s",
      "created": "5/15/2026, 1:17:55 PM",
      "completed": "5/15/2026, 1:25:36 PM",
      "message": "Completed",
      "questions": [
        {
          "number": "1",
          "score": 3.5,
          "max_score": 5,
          "rationale": "...",
          "correct": ["..."],
          "missing": ["..."],
          "improve": ["..."],
          "visible_evidence": ["..."],
          "evidence_used": ["..."]
        }
      ]
    }
  ]
}
```

The renderer is defensive: it accepts strings, numbers, missing lists, and alternate key names like `awarded_marks`, `max_marks`, `correct_elements`, `missing_or_incorrect_elements`, and `improvement_suggestions`.
