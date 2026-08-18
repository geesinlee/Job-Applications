# Gate 10 Design Spec: Interactive Evidence Discovery & Tailored CV Generation

**Date:** August 18, 2026  
**Status:** Design Phase  
**Implemented by:** (TBD in implementation phase)

---

## Overview

Gate 10 enhances the job application workflow with **deterministic, interactive evidence discovery**. Instead of purely automatic CV generation (Gate 9), users now answer clarifying questions about skills and experience not captured in their base CV, gather new evidence, re-score match against the JD, and iteratively review/refine the tailored CV before finalizing.

**Goal:** Improve UX predictability and outcome quality by grounding the workflow in facts/evidence and best practices, not freestyle Claude Desktop decisions.

---

## Architecture

### Deployment Model

```
Claude Desktop / Gemini / ChatGPT (any LLM)
         ↓ MCP Protocol
    pi-4 HTTP Server (always-on)
      ├─ LangChain Agent Orchestrator (new)
      ├─ Existing MCP Tools (enhanced)
      ├─ Evidence Backend (Postgres on NAS)
      └─ State Persistence (tracker.json on NAS)
         ↓ NFS
    NAS Shared Storage
      ├─ tracker.json (application records + workflow state)
      ├─ profile.json (candidate profile)
      ├─ Company folders (JD, CV, artifacts)
      └─ Postgres (StructuredEvidence + application-scoped evidence)
```

**Key design principle:** Server is stateful orchestrator. Any LLM client can pick up a workflow mid-flight by querying `get_workflow_state(application_id)`.

---

## Workflow Definition

### Job Application Workflow (Gate 10)

**Input:** Job description (file path or URL)  
**Output:** Tailored CV (saved to company folder) + gathered evidence (in tracker.json)

```
Step 1: INGEST JD
   Tool: ingest_jd(jd_path_or_url, application_id)
   ├─ Extract structured fields: must-haves, nice-to-haves, implicit skills, role level
   ├─ Save to JD.md in company folder
   └─ Store analysis in application record

Step 2: INITIAL MATCH SCORE
   Tool: score_match(profile, jd_analysis)
   ├─ Match score = (profile_skills ∩ jd_skills) / jd_skills
   ├─ Return: match_score (0-1), gap_analysis (missing skills/experience)
   
Step 3: DECISION GATE
   IF match_score >= 0.80 → SKIP to Step 6 (high confidence, no clarification needed)
   ELSE → proceed to Step 4

Step 4: INTERACTIVE EVIDENCE DISCOVERY LOOP
   (Repeat until user says "done" OR match_score >= 0.75)
   
   4a. [AGENT] Generate clarifying questions
       Tool: generate_clarifying_questions(jd_gaps, gathered_evidence_so_far)
       ├─ LangChain agent analyzes gaps
       ├─ Generates natural follow-ups: "Do you have experience with X?"
       ├─ Avoids redundant questions (checks already-answered)
       └─ Return: [ { question_id, question_text, field_type }, ... ]
   
   4b. [USER INPUT] User responds to questions via Claude Desktop
       Input: { question_id: response, ... }
   
   4c. [PERSIST] Add evidence to store
       Tool: add_evidence_from_user_input(application_id, question_responses)
       ├─ Create StructuredEvidence entries (Postgres)
       ├─ Store in application.gathered_evidence (tracker.json)
       └─ Return: { evidence_added: [...], timestamp }
   
   4d. [RESCORE] Recalculate match
       Tool: score_match(profile_with_new_evidence, jd_analysis)
       ├─ Match score now includes both base + gathered evidence
       └─ Return: { new_match_score, confidence, remaining_gaps }
   
   4e. [FEEDBACK] Show user progress
       Return to Claude Desktop: "Match improved from 62% → 78%. Remaining gaps: [...]"
   
   4f. [DECISION] Continue or stop?
       IF user says "done" OR match_score >= 0.75 → go to Step 5
       ELSE → repeat 4a-4f

Step 5: GENERATE TAILORED CV (DRAFT)
   Tool: generate_cv_from_jd_with_evidence(application_id, jd_analysis)
   ├─ Use updated evidence (base + gathered during workflow)
   ├─ Match evidence against JD skills
   ├─ Assemble CV with deduplication
   └─ Return: { draft_cv_markdown, match_confidence, ranking_rationale }

Step 6: ITERATIVE CV REVIEW
   (Repeat until user confirms OR requests changes)
   
   6a. [SHOW] Display draft CV to user
       Return to Claude Desktop: "Here's your tailored CV for Gartner SAE role"
   
   6b. [USER DECISION]
       IF user confirms → go to Step 7
       IF user requests changes → proceed to 6c
   
   6c. [REVISE] Gather feedback + regenerate
       Tool: revise_cv(application_id, feedback)
       ├─ Feedback types: "emphasize X", "remove Y", "add Z", "rephrase section"
       ├─ Regenerate or update CV
       └─ Return: { revised_cv_markdown }
   
   6d. [LOOP] Show revised CV → user decides → repeat until confirmed

Step 7: FINALIZE CV
   Tool: save_tailored_cv(application_id, final_cv_markdown)
   ├─ Save to company folder: CV_tailored.md
   ├─ Create cv_diff_summary.md (changes from base CV)
   ├─ Update tracker: application.cv_finalized = true
   └─ Return: { cv_path, summary }

Step 8: WORKFLOW COMPLETE
   Handover artifacts ready:
   ├─ JD.md (in company folder)
   ├─ CV_tailored.md (in company folder)
   ├─ application record with gathered_evidence (in tracker.json)
   └─ Ready for Gate 11 (cover letter + interview prep)
```

---

## MCP Tools (Gate 10)

### New Tools

| Tool | Signature | Purpose | Returns |
|------|-----------|---------|---------|
| `start_job_application_workflow` | `(jd_path_or_url: str, application_id: str)` | Begin workflow, ingest JD, return initial state | `{ stage: "gaps_identified", match_score: float, questions: [...], gaps: [...] }` |
| `generate_clarifying_questions` | `(application_id: str, jd_analysis: dict, exclude_answered: bool = true)` | LangChain agent generates follow-up questions | `{ questions: [ { id, text, field_type }, ... ], reasoning: str }` |
| `answer_clarifying_questions` | `(application_id: str, answers: dict)` | Accept user responses, persist evidence, rescore | `{ evidence_added: [...], new_match_score: float, remaining_gaps: [...] }` |
| `generate_cv_draft` | `(application_id: str)` | Create tailored CV from current evidence | `{ draft_cv: str (markdown), match_confidence: float, rationale: str }` |
| `revise_cv` | `(application_id: str, feedback: str)` | Update CV based on user feedback | `{ revised_cv: str (markdown), changes: [...] }` |
| `confirm_cv` | `(application_id: str)` | Finalize CV, save to file system | `{ status: "cv_finalized", cv_path: str, summary: str }` |
| `get_workflow_state` | `(application_id: str)` | Retrieve current workflow state (for resuming) | `{ stage: str, match_score: float, gathered_evidence: [...], pending_confirmations: [...] }` |

### Enhanced Existing Tools

- **`ingest_jd`** — Now stores JD analysis in application record (not just file)
- **`score_match`** — Now returns gap_analysis alongside score
- **`analyse_gaps`** — Returns structured gaps for question generation
- **`generate_cv_from_jd_with_evidence`** (Gate 9) — Used internally by `generate_cv_draft`

### Tool Implementation Notes

**`start_job_application_workflow`:**
- Calls `ingest_jd` internally
- Calls `score_match` to get initial gaps
- If match_score >= 0.80, skips to Step 6 (informs user, asks to proceed to CV review)
- If match_score < 0.80, proceeds to interactive loop

**`generate_clarifying_questions`:**
- Uses LangChain agent to synthesize clarifying questions from JD gaps
- Agent prompt: "Identify 3-5 most impactful missing skills/experience. For each, generate a natural question for the user."
- Avoids re-asking already-answered questions
- Returns structured questions (not free-form text)

**`answer_clarifying_questions`:**
- Validates responses match expected field types
- Creates StructuredEvidence entries in Postgres
- Updates application.gathered_evidence in tracker.json
- Calls `score_match` to rescore
- Returns progress to user (old score → new score, remaining gaps)

**`generate_cv_draft`:**
- Retrieves base profile + original evidence + gathered evidence
- Calls Gate 9's `CVGenerationService.generate` with combined evidence
- Returns draft + confidence + rationale (why certain evidence selected)

**`revise_cv`:**
- Accepts structured feedback: `{ type: "emphasize" | "remove" | "rephrase", field: str, detail?: str }`
- Updates CV or re-runs generation with modified evidence weights
- Returns revised CV

**`confirm_cv`:**
- Saves final CV to `company_folder/CV_tailored.md`
- Generates `cv_diff_summary.md` (line-by-line diff from base CV)
- Updates tracker: `application.cv_finalized = true`, `application.cv_tailored_path = "..."`
- Returns success confirmation

**`get_workflow_state`:**
- Returns entire workflow state: stage, match_score, gathered_evidence, pending confirmations, user feedback history
- Enables workflow resumption if session interrupted

---

## Data Model

### Application Record (tracker.json)

Enhanced structure for a single application:

```json
{
  "id": "gartner_sae_2026",
  "company": "Gartner",
  "role": "Strategic Account Executive",
  "stage": "cv_finalized",
  "created_at": "2026-08-18T10:00:00Z",
  "jd_analysis": {
    "must_haves": ["enterprise account management", "SaaS experience"],
    "nice_to_haves": ["analyst relations", "market research"],
    "implicit_skills": ["strategic thinking", "stakeholder management"],
    "role_level": "Senior",
    "extracted_at": "2026-08-18T10:05:00Z"
  },
  "workflow_state": {
    "current_stage": "cv_finalized",
    "initial_match_score": 0.62,
    "final_match_score": 0.78,
    "clarification_rounds": 2,
    "questions_asked": 7,
    "evidence_gathered": [
      {
        "source": "user_input",
        "question": "Do you have experience managing enterprise accounts?",
        "answer": "Yes, I managed 5 enterprise accounts at Acme, each $10M+ ARR",
        "evidence_id": "ev_9384",
        "added_at": "2026-08-18T10:15:00Z"
      }
    ]
  },
  "cv_finalized": true,
  "cv_tailored_path": "Gartner/CV_tailored.md",
  "cv_diff_summary_path": "Gartner/cv_diff_summary.md",
  "follow_up_date": "2026-08-25T09:00:00Z"
}
```

### Evidence Persistence (Two-Level)

**Level 1: Permanent Evidence Store (Postgres)**
- `StructuredEvidence` table (from Gate 9)
- Example: `{ evidence_id: "ev_9384", company: "Acme", role: "Account Manager", achievement: "Managed 5 enterprise accounts, each $10M+ ARR", tags: ["enterprise", "account_management"] }`

**Level 2: Application-Scoped Evidence (tracker.json)**
- `application.workflow_state.evidence_gathered`
- Links back to Postgres evidence_id
- Includes question context (what was asked, why)
- Example: `{ source: "user_input", question: "...", answer: "...", evidence_id: "ev_9384" }`

**Why two levels:**
- Permanent store: Reuse across future applications, builds corpus of achievements
- Application-scoped: Context for *this specific* application (why evidence matters for this JD)

---

## LangChain Integration

### Agent Architecture

**Workflow Agent** (runs on pi-4 in the MCP server process)

```python
from langchain.agents import AgentExecutor, create_react_agent
from langchain.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI

# Tools available to agent
tools = [
  StructuredTool(func=ingest_jd, ...),
  StructuredTool(func=score_match, ...),
  StructuredTool(func=generate_clarifying_questions, ...),
  StructuredTool(func=add_evidence_from_user_input, ...),
  StructuredTool(func=generate_cv_draft, ...),
  ...
]

# LLM model
llm = ChatGoogleGenerativeAI(model="gemini-flash-latest")

# Create agent
agent = create_react_agent(llm, tools, prompt=WORKFLOW_PROMPT)
executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# Run workflow
result = executor.invoke({
  "input": "Start job application workflow for Gartner SAE role (jd_path, app_id)"
})
```

**Why LangChain on the server:**
- Agent state is persistent (can pause/resume)
- Server owns the workflow state (not the client)
- Deterministic execution (same inputs → same outputs)
- Device-agnostic (Claude Desktop, Gemini, ChatGPT all call the same orchestration)

### LangChain vs. Custom Orchestration

**LangChain approach (chosen):**
- ✅ Flexible agent reasoning (can adapt to novel edge cases)
- ✅ Natural language workflow definition (agent reads task, decides steps)
- ✅ Tool calling is native (integrates with MCP tools seamlessly)
- ✅ Supports dynamic branching (if condition → different path)
- ⚠️ Adds dependency, slightly higher latency

**Custom state machine (alternative, not chosen):**
- ✅ Lighter weight, lower latency
- ✅ Explicit state transitions (easier to debug)
- ⚠️ Requires hardcoded workflow definition
- ⚠️ Less flexible for edge cases

---

## Data Flow: Evidence Collection & Re-Scoring

### User Input → Persistent Evidence

```
1. User answers clarifying question in Claude Desktop
   Input: { question_id: "q_7", response: "Yes, I managed 5 enterprise accounts..." }

2. MCP Tool: answer_clarifying_questions(application_id, answers)
   
3. Inside tool:
   a) Validate response format
   b) Create StructuredEvidence entry (Postgres)
      INSERT INTO structured_evidence (
        user_id, description, tags, source_type, application_id
      ) VALUES (...)
      → Returns evidence_id
   
   c) Link to application (tracker.json)
      application.workflow_state.evidence_gathered.append({
        source: "user_input",
        question: "Do you have experience managing enterprise accounts?",
        answer: "Yes, I managed 5 enterprise accounts...",
        evidence_id: "ev_9384",
        added_at: "2026-08-18T10:15:00Z"
      })
   
   d) Rescore match
      score_match(
        profile={base_skills + gathered_evidence},
        jd_analysis={extracted_from_jd}
      )
      → match_score: 0.62 → 0.78

4. Return to Claude Desktop
   {
     evidence_added: [{ evidence_id: "ev_9384", text: "... enterprise accounts..." }],
     new_match_score: 0.78,
     remaining_gaps: ["analyst relations"],
     progress: "Match improved from 62% to 78%. One gap remains: analyst relations experience."
   }
```

**Key principle:** Evidence is immutable once added (for audit trail). Corrections happen via new evidence entries.

---

## Integration with Claude Desktop / Other LLMs

### Interaction Flow

```
User: "Let's apply to Gartner SAE role"

Claude Desktop: "I'll help. Let me start the application workflow."
→ MCP Call: start_job_application_workflow(
    jd_path="Gartner/Gartner Strategic Account Executive.pdf",
    application_id="gartner_sae_2026"
  )

Server: Ingests JD, runs initial match score (62%). 
→ Returns: {
  stage: "gaps_identified",
  match_score: 0.62,
  gaps: ["strategic account planning", "enterprise SaaS experience", "analyst relations"],
  questions: [
    { id: "q_1", text: "Do you have experience managing strategic accounts?" },
    { id: "q_2", text: "Have you worked in SaaS companies or roles?" },
    ...
  ]
}

Claude Desktop: "I found a few gaps in your profile. Let me ask you some clarifying questions:

1. Do you have experience managing strategic accounts (accounts with $5M+ value)?
2. Have you worked in SaaS companies or roles?
3. Do you have experience managing analyst relationships (Gartner, Forrester, etc.)?

Please answer yes/no and provide details if yes."

User: "Yes to all three. For strategic accounts, I managed 5 at Acme, each $10M+. For SaaS, I was at Salesforce for 3 years. For analyst relations, I briefed Gartner analysts on our roadmap quarterly."

Claude Desktop: "Great! Let me capture that evidence."
→ MCP Call: answer_clarifying_questions(
    application_id="gartner_sae_2026",
    answers={
      q_1: "Yes, managed 5 enterprise accounts at Acme, each $10M+ ARR",
      q_2: "Yes, 3 years at Salesforce as Account Executive",
      q_3: "Yes, briefed Gartner analysts quarterly on our roadmap"
    }
  )

Server: Adds evidence to Postgres + tracker.json. Rescores match (62% → 78%).
→ Returns: {
  evidence_added: [...3 evidence items...],
  new_match_score: 0.78,
  remaining_gaps: ["industry knowledge of analyst market"],
  progress: "Match improved from 62% → 78%. Remaining gap: industry knowledge of analyst market."
}

Claude Desktop: "Excellent! Your match improved to 78%. One small gap remains: industry knowledge of the analyst market. Do you want me to generate your tailored CV now, or ask more clarifying questions?"

User: "Generate the CV."

Claude Desktop: "Let me create your tailored CV for the Gartner role."
→ MCP Call: generate_cv_draft(application_id="gartner_sae_2026")

Server: Uses Gate 9's CVGenerationService with combined evidence (base + gathered).
→ Returns: {
  draft_cv: "[Markdown CV with matched evidence in Gartner-relevant language]",
  match_confidence: 0.78,
  rationale: "Highlighted: enterprise account management (5 accounts), SaaS experience (Salesforce), analyst relations. Downplayed: technical skills, less relevant for SAE role."
}

Claude Desktop: "Here's your tailored CV for the Gartner SAE role:

[Shows draft CV]

Does this look good? I can revise specific sections if needed (emphasize leadership, remove technical details, rephrase specific bullets, etc.)"

User: "Looks good, but can you emphasize the analyst relations experience more?"

Claude Desktop: "Let me revise."
→ MCP Call: revise_cv(
    application_id="gartner_sae_2026",
    feedback={ type: "emphasize", field: "analyst_relations", detail: "Make it clear I regularly engage with analyst firms" }
  )

Server: Regenerates CV with adjusted weights/phrasing.
→ Returns: { revised_cv: "[Updated markdown]", changes: [...] }

Claude Desktop: "Updated! Here's the revised CV with analyst relations emphasized more:

[Shows revised CV]

Ready to finalize?"

User: "Yes, let's go."

Claude Desktop: "Finalizing..."
→ MCP Call: confirm_cv(application_id="gartner_sae_2026")

Server: Saves CV to Gartner/CV_tailored.md, generates diff summary, updates tracker.
→ Returns: {
  status: "cv_finalized",
  cv_path: "Gartner/CV_tailored.md",
  summary: "Your tailored CV is ready. Changes from base CV: emphasized analyst relations (3 bullets), kept enterprise account management experience, removed Python skills section (not relevant)."
}

Claude Desktop: "Done! Your tailored CV for Gartner SAE is ready at Gartner/CV_tailored.md. 

Next steps (Gate 11): Generate cover letter and prepare for interviews."
```

**Key behaviors:**
- Server drives determinism (workflow state, decision gates)
- Claude Desktop orchestrates UX (asks questions, shows drafts, requests confirmations)
- Evidence persists on server (reusable, auditable)
- Workflow is resumable (call `get_workflow_state(app_id)` to resume mid-flight)

---

## Testing Strategy

### Unit Tests

- **LangChain agent initialization:** Agent starts, has correct tools available
- **Question generation:** Agent generates relevant clarifying questions from gaps
- **Evidence persistence:** Evidence is saved to Postgres + tracker.json correctly
- **Match re-scoring:** Combining base + new evidence updates score as expected
- **CV generation with evidence:** CVGenerationService uses combined evidence

### Integration Tests

- **Full workflow (happy path):** Ingest JD → gaps identified → ask questions → gather evidence → rescore → generate CV → review → finalize
- **Workflow resume:** Save workflow state mid-flight, retrieve with `get_workflow_state`, continue from same point
- **High initial match (≥0.80):** Skip clarification loop, go straight to CV generation
- **Evidence deduplication:** Don't add duplicate evidence to store
- **CV revision:** Feedback loop (revise → show → confirm) works correctly

### Determinism Tests

- **Same inputs → same outputs:** Same JD + profile + evidence should generate identical CV (modulo timestamps)
- **Agent consistency:** LangChain agent makes the same workflow decisions with the same inputs

### Regression Tests

- **Gate 9 still works:** Evidence extraction, CV generation, backend abstraction not broken
- **Existing MCP tools:** `ingest_jd`, `score_match`, etc. still work as before

---

## Handover Artifacts

### Per Application (Gate 10 Completion)

Each application folder will contain:

```
Company/
├── JD.md                          # Ingested job description (structured fields + original text)
├── CV_tailored.md                 # Final tailored CV
├── cv_diff_summary.md             # What changed from base CV
├── [Original JD file]             # Preserved original PDF/document
└── [Future: research, pitch, cover letter from Gate 11+]
```

### tracker.json Entries

Each application record includes:

```json
{
  "id": "company_role_2026",
  "jd_analysis": { ... },
  "workflow_state": {
    "current_stage": "cv_finalized",
    "match_score": 0.78,
    "evidence_gathered": [ ... ]
  },
  "cv_finalized": true,
  "cv_tailored_path": "Company/CV_tailored.md"
}
```

### Evidence Store

New evidence entries in Postgres `StructuredEvidence` table:
- Linked back to applications (via application_id foreign key)
- Tagged with source ("user_input")
- Timestamped for audit trail

---

## Known Limitations & Future Work

### Gate 10 (Not Included)

- **No cover letter or interview prep** — Gate 11 task
- **LLM context limits** — As evidence grows, may need semantic search (Gate 11+)
- **No multi-round verification** — User gathers evidence once; could add "verify earlier responses" flow
- **No evidence editing UI** — Edit via Postgres directly or ask clarifying questions again

### Gate 11+ (Future)

- **Interview prep orchestration:** Research company, profile interviewer, prep questions, guess interview questions
- **Cover letter generation:** From evidence + company research
- **Notification system:** Send reminders for follow-ups, interviews
- **Bulk application workflow:** 10+ applications in parallel

---

## Success Criteria

✅ Deterministic workflow execution (same inputs → same outputs)  
✅ Interactive evidence discovery loop (ask → respond → gather → rescore → CV → review)  
✅ Evidence persisted (permanent store + application-scoped)  
✅ CV generation uses combined evidence (base + gathered)  
✅ Workflow resumable (call `get_workflow_state` to resume)  
✅ Device-agnostic (works with Claude Desktop, Gemini, ChatGPT via MPC)  
✅ Full test coverage (unit + integration + determinism tests)  
✅ Handover artifacts (JD, CV, evidence) ready for Gate 11

---

## References

- **Gate 9 Implementation:** `docs/superpowers/gate9/IMPLEMENTATION_NOTES.md`
- **Existing MCP Server:** `job_applications_mcp_server.py`
- **Tracker Schema:** `README.md` (Company Folder Structure section)
- **Evidence Backend:** `src/evidence_backend.py` (PostgresEvidenceBackend)
