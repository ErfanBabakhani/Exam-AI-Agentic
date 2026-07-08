from __future__ import annotations

import re
from collections.abc import Iterable
from fractions import Fraction

from grading_engine.schemas import RubricQuestion


def _normalize_math_symbols(text: str) -> str:
    replacements = {
        "≤": "<=",
        "≥": ">=",
        "−": "-",
        "–": "-",
        "—": "-",
        "×": "*",
        "·": "*",
    }
    normalized = text
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def _fraction_decimal_variants(text: str) -> set[str]:
    variants: set[str] = set()
    for numerator, denominator in re.findall(r"(?<!\d)(\d{1,6})\s*/\s*(\d{1,6})(?!\d)", text):
        try:
            value = Fraction(int(numerator), int(denominator))
        except (ValueError, ZeroDivisionError):
            continue
        decimal_value = float(value)
        for precision in (1, 2, 3, 4):
            rounded = f"{decimal_value:.{precision}f}".rstrip("0").rstrip(".")
            if rounded:
                variants.add(rounded)
    return variants


def _variants_for_text(text: str) -> list[str]:
    normalized = _normalize_math_symbols(text).strip()
    collapsed = " ".join(normalized.split())
    compact = collapsed.replace(" ", "")
    variants = {normalized, collapsed, collapsed.lower(), compact, compact.lower()}
    variants.update(_fraction_decimal_variants(normalized))
    return [item for item in variants if item]


def build_equivalence_seeds(rubric_questions: Iterable[RubricQuestion]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for question in rubric_questions:
        variants: set[str] = set()
        for criterion in question.criteria:
            variants.update(_variants_for_text(criterion.expected_answer))
        result[question.question_id] = sorted(variants)
    return result
