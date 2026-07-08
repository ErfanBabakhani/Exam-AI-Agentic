from __future__ import annotations

SAMPLE_REPORT = {
    "title": "AI Grading Report",
    "subtitle": "Rubric-linked evaluation with evidence and improvement guidance",
    "brand": "Zanista AI",
    "generated_at": "2026-05-15 14:35",
    "runs": [
        {
            "status": "completed",
            "student_file": "2.pdf",
            "exam_file": "Homework_3_sols.pdf",
            "score": 10,
            "max_score": 10,
            "duration": "47.0s",
            "created": "5/15/2026, 1:17:55 PM",
            "completed": "5/15/2026, 1:23:57 PM",
            "message": "Completed",
            "questions": [
                {
                    "number": "1",
                    "score": 5,
                    "max_score": 5,
                    "rationale": "The response earns full credit because it satisfies the key rubric criteria: the nullcline setup is correct, the slope condition is derived, and the final admissible parameter range is stated clearly.",
                    "correct": [
                        "Correct nullcline setup and geometric reasoning are visible.",
                        "Correct slope condition leading to the required threshold is stated.",
                        "Correct lower and upper bounds are combined into the final range.",
                    ],
                    "visible_evidence": [
                        "Page 1: Student writes the nullclines and sketches the piecewise-linear phase-plane argument.",
                        "Page 1: Final inequality range is written clearly and matches the rubric.",
                    ],
                    "evidence_used": [
                        "The setup, slope condition, and final combined range directly support full credit.",
                    ],
                },
                {
                    "number": "2",
                    "score": 5,
                    "max_score": 5,
                    "rationale": "The response earns full credit because it sets up the required moment-of-inertia integrals, gives values consistent with the expected results up to rounding, and concludes that beam B resists bending better based on the larger second moment of area.",
                    "correct": [
                        "Correct moment-of-inertia setup for both shapes.",
                        "Final values are consistent with the expected results up to rounding.",
                        "Correct comparison and bending-resistance conclusion.",
                    ],
                    "visible_evidence": [
                        "Page 2: Student computes both moments of inertia using integrals over the cross-section.",
                        "Page 2: Student writes that beam B has the larger moment and resists bending better.",
                    ],
                    "evidence_used": [
                        "The integral setup, final values, and comparison all align with the rubric.",
                    ],
                },
            ],
        },
        {
            "status": "completed",
            "student_file": "7.pdf",
            "exam_file": "Homework_3_sols.pdf",
            "score": 8.5,
            "max_score": 10,
            "duration": "41.4s",
            "created": "5/15/2026, 1:17:55 PM",
            "completed": "5/15/2026, 1:18:44 PM",
            "message": "Completed",
            "questions": [
                {
                    "number": "1",
                    "score": 5,
                    "max_score": 5,
                    "rationale": "The response earns full credit because the visible work shows the correct setup, slope comparison, endpoint conditions, and final parameter range.",
                    "correct": [
                        "Correct slope condition and threshold.",
                        "Correct lower and upper bounds.",
                        "Correct final range for periodic behaviour.",
                    ],
                    "visible_evidence": [
                        "Page 1: Student writes the nullclines, slope comparison, and final parameter range.",
                    ],
                    "evidence_used": [
                        "The final range and supporting inequalities match the rubric.",
                    ],
                },
                {
                    "number": "2",
                    "score": 3.5,
                    "max_score": 5,
                    "rationale": "The response earns partial credit for using the correct moment-of-inertia method and giving the correct qualitative conclusion. Marks are lost because the numerical values shown in the current transcription do not fully match the expected results, and the setup should be checked carefully.",
                    "correct": [
                        "Uses y^2 integrals about the neutral axis for both shapes.",
                        "Correctly concludes that beam B resists bending better.",
                    ],
                    "missing": [
                        "The evaluated values are not fully verified against the expected results.",
                        "Units and notation should be written more clearly.",
                    ],
                    "improve": [
                        "Check the geometry and width factors for each strip.",
                        "Recompute final values before comparing the beams.",
                    ],
                    "visible_evidence": [
                        "Page 2: Student writes moment-of-inertia integrals for both shapes and concludes that beam B is better.",
                    ],
                    "evidence_used": [
                        "The method and conclusion earn credit; numerical verification limits the score.",
                    ],
                },
            ],
        },
    ],
}
