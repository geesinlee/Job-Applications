# Fabrication Guard: 3 Options for CV Rewording Approval

## Problem

During the Gate 10 CV workflow, Claude often rewrites achievement statements for better tailoring to a job description while keeping metrics intact:

**Original:** "Led a team of 5 engineers to deliver $2M ARR platform"  
**Reworded:** "Managed a 5-person engineering team that delivered $2M ARR in new products"

The original fabrication guard rejected this even though:
- ✓ Numbers unchanged (5 is still 5, $2M is still $2M)
- ✓ Meaning preserved (leadership role clear in both versions)
- ✗ Exact line doesn't match (triggers false alarm)

## Solution: 3 Options

All three can be used together in a flexible workflow:

---

## Option 1: `allow_rewording` Flag

**Simple, direct approval mechanism.**

### What it does

Adds an `allow_rewording` parameter to `save_tailored_cv()`:

```python
save_tailored_cv(
    company="Acme",
    content=proposed_cv,
    allow_rewording=True  # ← New parameter
)
```

### How it works

1. Combines smart guard validation with manual approval
2. Smart guard checks:
   - Are all protected numbers still present?
   - Is string similarity >70%?
3. If issues found and rewording allowed, tool returns:
   ```json
   {
     "error": "requires_approval",
     "message": "Content changes detected in protected sections",
     "altered_segments": [...],
     "analysis": {...},
     "requires_review": true
   }
   ```
4. User reviews the returned analysis and can either:
   - Fix the CV and retry
   - Approve by calling without allow_rewording if satisfied

### When to use

- Quick approval after review
- You've already checked the changes manually
- Numbers are clearly preserved
- Want minimal back-and-forth

### Example workflow

```
1. Claude rewrites CV
2. You spot the change and recognize it's safe
3. save_tailored_cv(..., allow_rewording=true)
4. Tool approves (or returns analysis for review)
```

---

## Option 2: `review_cv_changes()` Tool

**Dedicated tool for detailed pre-save analysis.**

### What it does

New MCP tool that analyzes proposed CV changes *before* saving:

```python
review_cv_changes(
    company="Acme",
    proposed_content=new_cv
)
```

### Returns detailed report

```json
{
  "status": "needs_review",  // "approved" | "needs_review" | "rejected"
  "protected_lines_analysis": {
    "total_protected_lines": 5,
    "exact_matches": [
      "Achieved $500K cost savings"
    ],
    "reworded_acceptable": [
      {
        "original": "Led team of 5 engineers",
        "similarity": 0.95
      }
    ],
    "reworded_risky": [
      {
        "original": "Delivered $2M ARR platform",
        "similarity": 0.82
      }
    ],
    "altered_unacceptable": []
  },
  "number_preservation": {
    "base_numbers": ["5", "$500K", "$2M"],
    "proposed_numbers": ["5", "$500K", "$2M"],
    "missing_numbers": [],
    "preserved": true
  },
  "overall_similarity": 0.91,
  "recommendations": [
    "✓ 1 line remains unchanged",
    "✓ 1 line reworded with high confidence (similarity >90%)",
    "⚠️ 1 line reworded with medium confidence (similarity 70-90%)"
  ],
  "next_steps": "Review risky rewording above, then call save_tailored_cv with allow_rewording=true"
}
```

### When to use

- Want detailed visibility into what changed
- Comparing multiple rewording options
- Training on what "acceptable rewording" looks like
- Building confidence in the system
- Need explicit approval trail for compliance

### Example workflow

```
1. Claude generates CV with rewording
2. review_cv_changes("Acme", content)
   → Returns detailed analysis
3. You review similarity scores
4. save_tailored_cv("Acme", content, allow_rewording=true)
   → Saves with approval
```

---

## Option 3: Smart Fabrication Guard (Default)

**Automatic intelligent validation.**

### What it does

Replaces exact-line matching with smart number-based validation. Enabled by default in `save_tailored_cv()`:

```python
save_tailored_cv(
    company="Acme",
    content=proposed_cv,
    use_smart_guard=True  # ← Default (no need to specify)
)
```

### How it works

Smart guard algorithm:

1. **Extract protected lines:** Sentences with numbers, $, %, ARR, quota, deal, target
2. **Extract metrics:** All numbers from both Base_CV and proposed CV
3. **Check number preservation:** Are all base numbers still present?
4. **Check similarity:** For each protected line:
   - If exact match: 100% similarity ✓
   - If missing: 0% similarity ✗
   - Otherwise: Fuzzy match using string similarity
5. **Decision logic:**
   - ✓ **PASS:** All numbers preserved AND all similarities >70%
   - ✗ **FAIL:** Missing numbers OR low similarity (<70%)

### Similarity scoring

- **>90%:** "Led team of 5" vs "Managed 5-person team" → Minor wording change, approved
- **70-90%:** "Delivered $2M ARR" vs "Brought in $2M annual revenue" → More substantial rewording, needs review
- **<70%:** "Achieved 5x growth" vs "Led large scale initiative" → Too different, rejected

### When to use

- Most of the time (it's the default!)
- Want automatic approval for safe rewording
- Don't need visibility into every change
- Trust numbers preservation as the key metric

### Example workflow

```
1. Claude rewrites CV
2. save_tailored_cv("Acme", content)
   → Smart guard automatically checks
   → Approves if: numbers preserved AND similarities >70%
   → Rejects if: missing numbers OR too different
   → Returns analysis in either case
```

---

## Combining the Options

All three options work together in a flexible workflow:

### Conservative workflow (maximum review)

```
# Step 1: Detailed analysis
analysis = review_cv_changes("Acme", content)

# Step 2: Review similarity scores
if analysis["status"] == "approved":
    result = save_tailored_cv("Acme", content)
elif analysis["status"] == "needs_review":
    # Review the "reworded_acceptable" and "reworded_risky" items
    result = save_tailored_cv("Acme", content, allow_rewording=true)
else:
    # Reject - too many changes
    print("Fix the CV first")
```

### Balanced workflow (smart guard + override)

```
# Step 1: Try smart guard (default)
result = save_tailored_cv("Acme", content)

if result.get("requires_review"):
    # Step 2: Approve with explicit flag
    result = save_tailored_cv("Acme", content, allow_rewording=true)
```

### Fast workflow (trust the guard)

```
# Just save - smart guard handles validation
result = save_tailored_cv("Acme", content)
# Done!
```

---

## Implementation Details

### Key functions

**`_extract_protected_numbers(text)`**
- Finds all metrics: numbers with %, $, SGD, €, £
- Returns: raw_figures list + unique set

**`_validate_protected_content_smart(base, new)`**
- Core validation engine
- Returns: (is_valid, altered_lines, analysis_dict)
- Analysis includes similarity scores per line

**`review_cv_changes(company, content)`**
- New MCP tool (Option 2)
- Returns: detailed report with recommendations

**`save_tailored_cv(..., allow_rewording, use_smart_guard)`**
- New parameters enable Options 1 and 3
- Backward compatible (smart guard is default)

### Configuration

```python
# Use smart guard (default)
use_smart_guard=True

# Allow rewording after review
allow_rewording=True

# Disable smart guard (revert to exact matching)
use_smart_guard=False
```

---

## Examples

### Example 1: Numbers preserved, minor rewording → AUTO-APPROVE

**Base CV:**
```
- Led a team of 5 engineers to deliver a $2M ARR product
```

**Proposed CV:**
```
- Managed a team of 5 talented engineers who delivered $2M ARR platform
```

**Smart guard check:**
- ✓ Both numbers present (5, $2M)
- ✓ Similarity 83.5%
- **Result: APPROVED** (numbers preserved, >70% similarity)

### Example 2: Number removed → REJECT

**Base CV:**
```
- Achieved 95% customer satisfaction rate
- Delivered $2M ARR product
```

**Proposed CV:**
```
- Achieved strong customer satisfaction
- Delivered $2M ARR product
```

**Smart guard check:**
- ✗ Missing number: "95"
- **Result: REJECTED** (numbers not preserved)

### Example 3: Exact match → AUTO-APPROVE

**Base CV:**
```
- Led a team of 5 engineers
```

**Proposed CV:**
```
- Led a team of 5 engineers
```

**Smart guard check:**
- ✓ Exact match (100% similarity)
- **Result: APPROVED**

---

## Testing

Run the test suite:

```bash
python3 test_fabrication_guard_options.py
```

Tests verify:
- Smart guard accepts safe rewording (numbers preserved)
- Smart guard rejects altered content (numbers missing)
- Exact matches always pass
- Similarity scoring works correctly

---

## FAQ

**Q: What if Claude rewrites in a way I don't like but metrics are preserved?**  
A: Call `review_cv_changes()` first to see the detailed changes, then decide to approve or reject.

**Q: Does allow_rewording=true skip all checks?**  
A: No! It still uses smart guard. It just returns analysis instead of rejecting on edge cases.

**Q: Can I disable the smart guard?**  
A: Yes: `save_tailored_cv(..., use_smart_guard=False)` reverts to exact-line matching.

**Q: What counts as "protected content"?**  
A: Lines containing:
- Numbers with %, $, SGD, €, £ (e.g., "5 engineers", "$2M", "95%")
- Keywords: ARR, quota, deal, target

**Q: What similarity threshold is used?**  
- >90%: Approved automatically
- 70-90%: Needs review (reworded_risky)
- <70%: Rejected unless allow_rewording=true

**Q: Can I override the thresholds?**  
A: Currently fixed in code. Edit `_validate_protected_content_smart()` if you need custom thresholds.

---

## Deployment

✅ Deployed to pi-4 on 2026-08-20  
✅ Ready for production use  
✅ Backward compatible with existing code

Both MCP tools (`review_cv_changes`, `save_tailored_cv`) are registered and available in Claude.
