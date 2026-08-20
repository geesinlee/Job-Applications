# Gate 10 Implementation Plan: Interactive Evidence Discovery & CV Workflow

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, LangChain-orchestrated job application workflow that interactively discovers user evidence, gathers new achievements, re-scores JD match, and generates a tailored CV through iterative review.

**Architecture:** LangChain React agents run on pi-4 MCP server, orchestrating tool calls. Evidence is stored in two layers (permanent Postgres + application-scoped tracker.json). MCP tools handle data persistence and LLM interactions. Any LLM client (Claude Desktop, Gemini, ChatGPT) calls the orchestration tools deterministically.

**Tech Stack:** FastMCP (existing), LangChain (new), langchain-google-genai, Prisma (existing), Postgres (existing), Python dataclasses, pytest.

---

## Task Summary

1. **Task 1:** Install Dependencies & Setup LangChain Infrastructure
2. **Task 2:** Enhance Evidence Models & Backend for Application-Scoped Evidence
3. **Task 3a:** Implement start_job_application_workflow Tool
4. **Task 3b:** Implement generate_clarifying_questions Tool
5. **Task 3c:** Implement answer_clarifying_questions Tool
6. **Task 3d:** Implement generate_cv_draft & revise_cv Tools
7. **Task 3e:** Implement confirm_cv & get_workflow_state Tools
8. **Task 4:** Register Tools with MCP Server
9. **Task 5:** Write Integration Tests for Full Workflow
10. **Task 6:** Documentation & Handover

---

## Full Plan Text

[Plan content saved above - see implementation steps in each task section]

See full plan details in the architecture and task breakdown sections of the design spec.

