export function WelcomePanel() {
  return (
    <div className="hero-card welcome-hero">
      <p className="eyebrow">AI Exam Grader</p>
      <h1>Welcome to AI Exam Grader.</h1>
      <p className="lede">
        Log in or create an account to upload exam papers, review AI-assisted grading results, and
        track previous submissions.
      </p>
      <div className="meta-grid">
        <div>
          <strong>Structured intake</strong>
          <p>Upload the exam or mark scheme once, then attach one or many student-answer PDFs.</p>
        </div>
        <div>
          <strong>Evidence-backed review</strong>
          <p>Inspect scored questions, rationale, evidence summaries, and teacher overrides.</p>
        </div>
        <div>
          <strong>Traceable history</strong>
          <p>Track previous submissions, export reports, and revisit stored grading runs later.</p>
        </div>
      </div>
    </div>
  );
}
