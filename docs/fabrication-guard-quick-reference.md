# Fabrication Guard: Quick Reference

## 3 Options for CV Rewording

| Option | Tool | Use Case | Command |
|--------|------|----------|---------|
| **1** | `allow_rewording` param | Manual approval | `save_tailored_cv(..., allow_rewording=true)` |
| **2** | `review_cv_changes()` | Detailed pre-save review | `review_cv_changes(company, content)` |
| **3** | Smart guard (default) | Auto-approve safe changes | `save_tailored_cv(...)` (just works!) |

---

## Recommended Workflow

### Fast (Trust the Guard)
```
save_tailored_cv(company, content)
→ Smart guard validates automatically
→ Done in 1 step!
```

### Balanced (Review + Approve)
```
result = save_tailored_cv(company, content)
if result.get("requires_review"):
    save_tailored_cv(company, content, allow_rewording=true)
```

### Thorough (Detailed Analysis)
```
analysis = review_cv_changes(company, content)
# Review: exact_matches, reworded_acceptable, reworded_risky
save_tailored_cv(company, content, allow_rewording=true)
```

---

## What Gets Approved Automatically

✅ **Numbers preserved**
- "Led 5 engineers" → "Managed 5-person team" ✓
- "$2M ARR" → "$2M annual revenue" ✓
- "95% satisfaction" → "95% customer satisfaction" ✓

✅ **Minor rewording** (>90% similar)
- "Delivered X" → "Built X" ✓
- "Achieved X" → "Accomplished X" ✓

---

## What Gets Rejected

❌ **Numbers removed**
- "Led 5 engineers" → "Led team" ✗
- "$2M ARR" → "Large revenue" ✗

❌ **Substantially different** (<70% similar)
- "Led team of 5" → "Was part of large initiative" ✗

❌ **Protected keywords altered**
- "ARR target" → "revenue goal" ✗

---

## Option 1: `allow_rewording=true`

When you've already reviewed and want to approve:

```python
save_tailored_cv(
    company="Acme",
    content=new_cv,
    allow_rewording=True
)
```

Returns: `{"status": "requires_approval", "analysis": {...}}`

---

## Option 2: `review_cv_changes()`

When you want detailed analysis first:

```python
analysis = review_cv_changes("Acme", new_cv)
```

Returns:
- `status`: "approved" / "needs_review" / "rejected"
- `protected_lines_analysis`: exact matches, reworded, altered
- `similarity_scores`: 0.0-1.0 per protected line
- `missing_numbers`: what metrics were dropped
- `recommendations`: what to fix

---

## Option 3: Smart Guard (Default)

When you trust the validation logic:

```python
save_tailored_cv(company="Acme", content=new_cv)
```

Smart guard automatically:
1. Checks all metrics preserved (5, $2M, 95%, etc.)
2. Scores similarity of reworded lines (0-100%)
3. Approves if numbers preserved AND >70% similar
4. Rejects if numbers missing OR too different

---

## Decision Tree

```
Does your proposed CV content:

1. Have all original numbers/metrics?
   NO  → Revise and try again
   YES → Continue

2. Use similar wording? (>70% match)
   NO  → Review carefully (review_cv_changes)
          then allow_rewording=true if you approve
   YES → Just save_tailored_cv() - approved!
```

---

## Examples

### ✅ This Passes Smart Guard
```
Base:     "Led a team of 5 engineers"
Proposed: "Managed 5-person engineering team"
Reason:   Numbers same (5), very similar wording (95%)
```

### ⚠️ This Needs Review
```
Base:     "Delivered $2M ARR platform"
Proposed: "Launched $2M ARR product line"
Reason:   Numbers same ($2M), medium similarity (82%)
→ Use: review_cv_changes() → allow_rewording=true
```

### ❌ This Gets Rejected
```
Base:     "Achieved 95% customer satisfaction"
Proposed: "High customer satisfaction"
Reason:   Lost number (95%)
→ Fix the CV and try again
```

---

## When to Use Which

**Use Smart Guard Alone:**
- Confident Claude's rewording is good
- Want fastest workflow
- Trust the number preservation check

**Add `review_cv_changes()`:**
- Want to see similarity scores
- Training yourself on edge cases
- Building confidence
- Compliance trail needed

**Use `allow_rewording=true`:**
- You've already reviewed the changes
- Smart guard had questions, you've decided
- Want explicit approval in the response

---

## Parameters

```python
save_tailored_cv(
    company: str,              # Company name (required)
    content: str,              # CV markdown (required)
    diff_summary: list = None, # Optional: custom diff entries
    allow_rewording: bool = False,  # Option 1: Manual approval
    use_smart_guard: bool = True,   # Option 3: Enable smart validation
)
```

Both new parameters are optional and have sensible defaults!

---

## Common Issues

**"fabrication_detected: Numbers altered"**
→ Check that all metrics (5, $2M, 95%) are in the proposed CV

**"requires_approval" status**
→ Review returned analysis, then call with `allow_rewording=true`

**"similarity too low"**
→ Use `review_cv_changes()` to see exactly what changed

---

## Testing

```bash
python3 test_fabrication_guard_options.py
```

Validates:
- Safe rewording approved ✓
- Altered content rejected ✓
- Numbers preserved checked ✓
- Similarity scored correctly ✓

---

## Summary

- **Smart Guard (default):** Fast, automatic, trusts number preservation
- **Review Tool:** Detailed, gives you visibility and control
- **Allow Rewording:** Manual override when you've already decided
- **All three work together:** Choose the workflow you prefer!
