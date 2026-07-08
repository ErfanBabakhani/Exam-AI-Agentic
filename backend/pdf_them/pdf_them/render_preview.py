from pathlib import Path
from sample_data import SAMPLE_REPORT
from renderer import render_grading_report_pdf

if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "grading_export_template_preview_g.pdf"
    render_grading_report_pdf(SAMPLE_REPORT, out)
    print(out)
