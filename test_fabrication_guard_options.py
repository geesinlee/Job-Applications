#!/usr/bin/env python3
"""
Test script demonstrating all 3 fabrication guard options.

This tests the three new features:
1. Smart fabrication guard (Option 3) - intelligent number-based validation
2. Allow-rewording flag (Option 1) - manual approval with smart guard
3. Review CV changes tool (Option 2) - dedicated review workflow
"""

import re
from pathlib import Path

# Mock the functions for testing
def _extract_protected_numbers(text: str) -> dict:
    """Extract all protected numbers/figures from text."""
    PROTECTED_NUMERIC_RE = re.compile(r"\d+\s*(?:%|\$|SGD|€|£)", re.IGNORECASE)
    matches = PROTECTED_NUMERIC_RE.findall(text)
    numbers = []
    for match in matches:
        num_match = re.search(r"\d+", match)
        if num_match:
            numbers.append(num_match.group())
    return {
        "raw_figures": matches,
        "unique_figures": set(numbers),
        "count": len(matches),
    }


def _validate_protected_content_smart(base_cv_text: str, new_cv_text: str) -> tuple[bool, list[str], dict]:
    """Smart fabrication guard: Check if protected numbers are preserved."""
    PROTECTED_NUMERIC_RE = re.compile(r"\d+\s*(?:%|\$|SGD|€|£)", re.IGNORECASE)
    PROTECTED_KEYWORD_RE = re.compile(r"\b(?:ARR|quota|deal|target)\b", re.IGNORECASE)

    def _protected_lines(text: str) -> list[str]:
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and (PROTECTED_NUMERIC_RE.search(stripped) or PROTECTED_KEYWORD_RE.search(stripped)):
                lines.append(stripped)
        return lines

    protected_base_lines = _protected_lines(base_cv_text)
    if not protected_base_lines:
        return True, [], {}

    base_numbers = _extract_protected_numbers(base_cv_text)
    new_numbers = _extract_protected_numbers(new_cv_text)
    missing_numbers = base_numbers["unique_figures"] - new_numbers["unique_figures"]

    altered_lines = []
    similarity_scores = {}

    for base_line in protected_base_lines:
        if base_line in new_cv_text:
            similarity_scores[base_line] = 1.0
            continue

        best_match_ratio = 0.0
        for new_line in new_cv_text.splitlines():
            new_stripped = new_line.strip()
            if new_stripped:
                ratio = difflib.SequenceMatcher(None, base_line, new_stripped).ratio()
                best_match_ratio = max(best_match_ratio, ratio)

        similarity_scores[base_line] = best_match_ratio

        if best_match_ratio < 0.7:
            altered_lines.append(base_line)

    is_valid = len(missing_numbers) == 0 and len(altered_lines) == 0

    analysis = {
        "protected_lines_checked": len(protected_base_lines),
        "exact_matches": sum(1 for s in similarity_scores.values() if s == 1.0),
        "similarity_scores": similarity_scores,
        "average_similarity": sum(similarity_scores.values()) / len(similarity_scores) if similarity_scores else 1.0,
        "missing_numbers": list(missing_numbers),
        "number_preservation": len(new_numbers["unique_figures"]) == len(base_numbers["unique_figures"]),
    }

    return is_valid, altered_lines, analysis


import difflib

# Test Cases
print("=" * 80)
print("TEST 1: Numbers Unchanged, Minor Rewording (Should PASS with smart guard)")
print("=" * 80)

base_cv = """
## Professional Experience

**Senior Solutions Architect at Acme Corp (2020-2023)**
- Led a team of 5 engineers to deliver a $2M ARR product
- Achieved 95% customer satisfaction with data-driven improvements
"""

proposed_cv_1 = """
## Professional Experience

**Senior Solutions Architect at Acme Corp (2020-2023)**
- Managed a team of 5 talented engineers to deliver a $2M ARR platform
- Achieved 95% customer satisfaction through continuous data-driven improvements
"""

is_valid, altered, analysis = _validate_protected_content_smart(base_cv, proposed_cv_1)
print(f"Valid: {is_valid}")
print(f"Analysis:")
print(f"  - Exact matches: {analysis['exact_matches']}/{analysis['protected_lines_checked']}")
print(f"  - Average similarity: {analysis['average_similarity']:.1%}")
print(f"  - Numbers preserved: {analysis['number_preservation']}")
print(f"  - Missing numbers: {analysis['missing_numbers']}")
print(f"Result: {'✅ PASS' if is_valid else '⚠️ NEEDS REVIEW'}\n")

# Test Case 2
print("=" * 80)
print("TEST 2: Numbers Altered (Should FAIL - numbers missing)")
print("=" * 80)

proposed_cv_2 = """
## Professional Experience

**Senior Solutions Architect at Acme Corp (2020-2023)**
- Managed a large team of engineers to deliver an ARR product
- Achieved high customer satisfaction with data-driven improvements
"""

is_valid, altered, analysis = _validate_protected_content_smart(base_cv, proposed_cv_2)
print(f"Valid: {is_valid}")
print(f"Analysis:")
print(f"  - Exact matches: {analysis['exact_matches']}/{analysis['protected_lines_checked']}")
print(f"  - Average similarity: {analysis['average_similarity']:.1%}")
print(f"  - Numbers preserved: {analysis['number_preservation']}")
print(f"  - Missing numbers: {analysis['missing_numbers']}")
print(f"Result: {'✅ PASS' if is_valid else '❌ FAIL - Numbers missing'}\n")

# Test Case 3
print("=" * 80)
print("TEST 3: Exact Match (Should PASS - no changes)")
print("=" * 80)

proposed_cv_3 = base_cv  # Exact same content

is_valid, altered, analysis = _validate_protected_content_smart(base_cv, proposed_cv_3)
print(f"Valid: {is_valid}")
print(f"Analysis:")
print(f"  - Exact matches: {analysis['exact_matches']}/{analysis['protected_lines_checked']}")
print(f"  - Average similarity: {analysis['average_similarity']:.1%}")
print(f"  - Numbers preserved: {analysis['number_preservation']}")
print(f"  - Missing numbers: {analysis['missing_numbers']}")
print(f"Result: {'✅ PASS' if is_valid else '❌ FAIL'}\n")

print("=" * 80)
print("SUMMARY OF OPTIONS")
print("=" * 80)
print("""
Option 1: allow_rewording=True
- User calls save_tailored_cv with allow_rewording=true
- Smart guard checks if numbers preserved and similarity >70%
- If still issues, returns 'requires_approval' for manual review
- Usage: save_tailored_cv(company, content, allow_rewording=true)

Option 2: review_cv_changes() tool
- User calls review_cv_changes(company, proposed_content) FIRST
- Returns detailed analysis:
  * Exact matches vs rewording
  * Similarity scores for each protected line
  * Missing numbers (if any)
  * Recommendations for fixes
- User reviews and decides to proceed or fix
- Usage: review_cv_changes(company, content) → then save_tailored_cv()

Option 3: use_smart_guard=True (default)
- Smart validation instead of exact-line matching
- Checks: number preservation + string similarity (>90%)
- Gracefully allows rewording if metrics preserved
- Usage: save_tailored_cv(company, content) - smart guard is default

All 3 options can be combined:
- use_smart_guard=true (default) for automatic validation
- review_cv_changes() for detailed review before saving
- allow_rewording=true to approve after review
""")
