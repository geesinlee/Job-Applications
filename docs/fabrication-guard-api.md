# Fabrication Guard: API Reference

## MCP Tools

### 1. `review_cv_changes()` (Option 2)

**Dedicated tool for pre-save CV analysis.**

#### Signature
```python
review_cv_changes(company: str, proposed_content: str) -> dict
```

#### Parameters
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `company` | str | Yes | Target employer name (e.g., "Acme") |
| `proposed_content` | str | Yes | The proposed CV content in Markdown |

#### Returns
```json
{
  "company": "Acme",
  "status": "approved" | "needs_review" | "rejected",
  
  "protected_lines_analysis": {
    "total_protected_lines": 5,
    
    "exact_matches": [
      "Achieved $500K cost savings",
      "Led a team of 5 engineers"
    ],
    
    "reworded_acceptable": [
      {
        "original": "Delivered $2M ARR platform",
        "similarity": 0.95
      }
    ],
    
    "reworded_risky": [
      {
        "original": "Managed large-scale initiative",
        "similarity": 0.82
      }
    ],
    
    "altered_unacceptable": [
      {
        "original": "Achieved 95% customer satisfaction",
        "similarity": 0.45
      }
    ]
  },
  
  "number_preservation": {
    "base_numbers": ["5", "$500K", "$2M", "95"],
    "proposed_numbers": ["5", "$500K", "$2M"],
    "missing_numbers": ["95"],
    "preserved": false
  },
  
  "overall_similarity": 0.84,
  
  "recommendations": [
    "✓ 1 line remains unchanged",
    "✓ 1 line reworded with high confidence (similarity >90%)",
    "⚠️ 1 line reworded with medium confidence (similarity 70-90%)",
    "❌ 1 line altered too much (missing 95)"
  ],
  
  "next_steps": "Fix the issues above before saving"
}
```

#### Status Values
- `"approved"`: All checks passed, ready to save
- `"needs_review"`: Some risky rewording, review and decide
- `"rejected"`: Changes too extensive, fix required

#### Example
```python
analysis = review_cv_changes("Acme", new_cv_content)

if analysis["status"] == "approved":
    save_tailored_cv("Acme", new_cv_content)
elif analysis["status"] == "needs_review":
    # Review similarity_scores and make decision
    save_tailored_cv("Acme", new_cv_content, allow_rewording=true)
else:
    print("Fix CV based on recommendations")
```

---

### 2. `save_tailored_cv()` Enhanced (Options 1 & 3)

**Enhanced with two new optional parameters.**

#### Signature
```python
save_tailored_cv(
    company: str,
    content: str,
    diff_summary: list | None = None,
    allow_rewording: bool = False,
    use_smart_guard: bool = True
) -> dict
```

#### Parameters
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `company` | str | - | Target employer name (required) |
| `content` | str | - | Tailored CV content in Markdown (required) |
| `diff_summary` | list | None | Optional: Custom diff entries |
| `allow_rewording` | bool | False | **(Option 1)** Allow manual rewording approval |
| `use_smart_guard` | bool | True | **(Option 3)** Use smart validation (default) |

#### Returns (Success Case)
```json
{
  "company": "Acme",
  "path": "/path/to/Acme/CV_tailored.md",
  "diff_summary_path": "/path/to/Acme/cv_diff_summary.md",
  "diff_entries": 3,
  "content_length": 2847,
  "saved": true,
  "cv_id": "cv-uuid-here",
  "version": "1.0",
  "status": "draft"
}
```

#### Returns (Smart Guard Issues - with `use_smart_guard=true`)
```json
{
  "error": "fabrication_detected" | "requires_approval",
  "message": "Protected content validation failed" | "Content changes detected",
  "altered_segments": ["line1", "line2"],
  "analysis": {
    "protected_lines_checked": 5,
    "exact_matches": 2,
    "similarity_scores": {
      "Led a team of 5": 0.95,
      "Delivered $2M": 0.82
    },
    "average_similarity": 0.89,
    "missing_numbers": [],
    "number_preservation": true
  },
  "suggestion": "Use allow_rewording=true to review changes"
}
```

#### Parameter Combinations

**Option 3 Only (Smart Guard - Default)**
```python
save_tailored_cv("Acme", content)
# use_smart_guard=True, allow_rewording=False (defaults)
```

**Option 1 Only (Manual Approval)**
```python
save_tailored_cv("Acme", content, allow_rewording=True)
# use_smart_guard=True, allow_rewording=True
```

**Hybrid (Smart Guard + Manual Override)**
```python
result = save_tailored_cv("Acme", content)
if result.get("requires_approval"):
    save_tailored_cv("Acme", content, allow_rewording=True)
```

**Legacy (Exact Matching)**
```python
save_tailored_cv("Acme", content, use_smart_guard=False)
# Reverts to exact-line matching (pre-smart-guard behavior)
```

---

## Helper Functions (Internal)

### `_extract_protected_numbers(text: str) -> dict`

Extracts all quantified metrics from text.

```python
def _extract_protected_numbers(text: str) -> dict:
    """
    Returns: {
        "raw_figures": ["5 engineers", "$2M", "95%"],
        "unique_figures": {"5", "2", "95"},
        "count": 3
    }
    """
```

### `_validate_protected_content_smart(base: str, new: str) -> tuple`

Core smart guard validation engine.

```python
def _validate_protected_content_smart(base_cv_text: str, new_cv_text: str) -> tuple:
    """
    Returns: (is_valid: bool, altered_lines: list, analysis: dict)
    
    is_valid = True if:
      - All protected numbers present in new text
      - AND all protected lines have similarity >70%
    
    analysis contains:
      - protected_lines_checked: int
      - exact_matches: int
      - similarity_scores: {line: score}
      - average_similarity: float (0-1)
      - missing_numbers: list
      - number_preservation: bool
    """
```

---

## Validation Rules

### Protected Content
Lines that trigger validation:

1. **Numeric figures** - Numbers with currency/percentage markers:
   - Matches: `\d+\s*(?:%|\$|SGD|€|£)`
   - Examples: "5 engineers", "$2M", "95%", "12 SGD"

2. **Protected keywords** - Business-specific terms:
   - Keywords: `ARR|quota|deal|target` (case-insensitive)
   - Examples: "ARR target", "quota exceeded", "deal closed"

### Similarity Scoring
Fuzzy string matching using `difflib.SequenceMatcher`:

- **1.0 (100%)**: Exact match
- **>0.9 (>90%)**: Minor rewording, automatically approved
  - Example: "Led team of 5" vs "Managed 5-person team"
- **0.7-0.9 (70-90%)**: Medium rewording, needs review
  - Example: "Delivered $2M ARR" vs "Brought in $2M annual revenue"
- **<0.7 (<70%)**: Substantial changes, rejected
  - Example: "Led 5-person team" vs "Was part of large initiative"

### Number Preservation
All unique numbers in base CV must appear in proposed CV:

```
Base:     "Led 5 engineers, $2M ARR, 95% satisfaction"
Proposed: "Led 5 engineers, delivered $2M ARR successfully"
Missing:  ["95"]
Result:   ❌ REJECTED (95% satisfaction number missing)
```

---

## Decision Tree

```
Propose new CV
    ↓
save_tailored_cv(company, content)
    ↓
use_smart_guard=True (default)?
    ├─ YES → Smart guard checks:
    │       1. Extract all protected metrics
    │       2. Check number preservation
    │       3. Calculate similarity scores
    │       ↓
    │   All numbers present AND similarity >70%?
    │       ├─ YES → ✅ SAVED
    │       └─ NO  → ⚠️ requires_approval
    │               ↓
    │           allow_rewording=True?
    │               ├─ YES → ✅ SAVED
    │               └─ NO  → ❌ fabrication_detected
    │
    └─ NO → Exact-line matching (legacy behavior)
           ↓
        All protected lines unchanged?
           ├─ YES → ✅ SAVED
           └─ NO  → ❌ fabrication_detected
```

---

## Configuration Examples

### Conservative (Detailed Review)

```python
# Step 1: Get detailed analysis
analysis = review_cv_changes("Acme", proposed_cv)

# Step 2: Review the analysis
print(f"Status: {analysis['status']}")
print(f"Similarity scores: {analysis['protected_lines_analysis']}")

# Step 3: Decide based on analysis
if analysis["status"] in ["approved", "needs_review"]:
    result = save_tailored_cv("Acme", proposed_cv, allow_rewording=True)
else:
    # Fix the CV and try again
    print("Issues to fix:", analysis['recommendations'])
```

### Balanced (Smart + Override)

```python
# Try smart guard
result = save_tailored_cv("Acme", proposed_cv)

# Override if issues and you're confident
if "requires_approval" in result.get("error", ""):
    result = save_tailored_cv("Acme", proposed_cv, allow_rewording=True)
```

### Fast (Just Trust It)

```python
# Smart guard handles everything
result = save_tailored_cv("Acme", proposed_cv)
# Done! Approved or returns analysis for review
```

---

## Error Codes

### `fabrication_detected`
Protected content violated:
- Numbers removed/altered
- Similarity too low (<70%)
- Required to use `allow_rewording=true` or fix CV

### `requires_approval`
Smart guard found issues but `allow_rewording=true`:
- Analysis returned for user review
- User can decide to save or fix

### `requires_review`
From `review_cv_changes()`:
- Some risky rewording detected
- Recommendations provided
- User should review before saving

---

## Testing

Run validation tests:

```bash
python3 test_fabrication_guard_options.py
```

Validates:
- Smart guard accepts safe rewording
- Smart guard rejects altered content
- Similarity scoring is accurate
- Number extraction works correctly

---

## Compatibility

✅ **Backward Compatible**
- Existing code works unchanged
- New parameters optional with sensible defaults
- `use_smart_guard=True` is default (smart validation)
- Can revert to exact matching with `use_smart_guard=False`

✅ **No Breaking Changes**
- Returns same structure on success
- Error structure enhanced (backward compatible)
- All existing integrations continue to work

---

## Performance

- **Smart guard check**: ~10-50ms per CV (linear in content size)
- **Number extraction**: ~5ms per CV
- **Similarity scoring**: ~20-40ms per protected line
- **Overall**: <100ms for typical CV (negligible overhead)

---

## Next Steps

1. **Use Option 3 (Smart Guard)** by default
2. **Use Option 2 (review_cv_changes)** when unsure
3. **Use Option 1 (allow_rewording)** for final approval
4. **Report edge cases** where thresholds need tuning

Questions? See `docs/fabrication-guard-options.md` for detailed guide.
