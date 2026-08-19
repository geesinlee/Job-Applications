"""LangChain workflow orchestrator for Gate 10 interactive evidence discovery."""

from __future__ import annotations

from typing import Any, Optional, Dict
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
import os


class WorkflowOrchestrator:
    """Orchestrates job application workflow using LangChain ReAct agent."""

    def __init__(self, model: str = None):
        """
        Initialize orchestrator with LLM and empty tools list.

        Args:
            model: Google Generative AI model name. Defaults to WORKFLOW_MODEL env var or gemini-flash-latest.

        Raises:
            ValueError: If GOOGLE_API_KEY is not set in environment.
        """
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not set in environment")

        self.model_name = model or os.getenv("WORKFLOW_MODEL", "gemini-flash-latest")
        self.llm = ChatGoogleGenerativeAI(
            model=self.model_name,
            temperature=0,  # Deterministic
            api_key=api_key
        )
        self.tools = []
        self.agent_executor = None

    def register_tool(self, tool: StructuredTool) -> None:
        """Register a tool with the orchestrator."""
        self.tools.append(tool)

    def initialize_agent(self) -> None:
        """Create and initialize the ReAct agent with registered tools."""
        if not self.tools:
            raise RuntimeError("No tools registered. Call register_tool() first.")

        prompt = PromptTemplate.from_template(
            """You are an expert job application workflow orchestrator.
Your role is to guide users through a deterministic job application workflow:

1. Ingest job description
2. Identify skill/experience gaps
3. Ask clarifying questions to discover undiscovered skills/experience
4. Gather new evidence
5. Re-score match
6. Generate tailored CV
7. Iteratively review and refine CV
8. Finalize and save

Use the available tools to execute each step. Be precise, deterministic, and grounded in facts.

Current task: {input}

Available tools: {tool_names}
"""
        )

        self.agent_executor = create_react_agent(
            self.llm,
            self.tools,
            prompt
        )

    def run_workflow(self, task: str) -> Dict:
        """
        Execute a workflow step and return results.

        Args:
            task: Task description/prompt for the workflow agent.

        Returns:
            Dict: Result dict containing agent output or error info.
                  On success: {"status": "success", "output": ...}
                  On error: {"status": "error", "error": error_message}

        Raises:
            RuntimeError: If no tools are registered before workflow execution.

        Note:
            Agent execution may timeout after extended periods. Callers should
            implement their own timeout handling if needed.
        """
        if not self.tools:
            raise RuntimeError("No tools registered. Call register_tool() first.")

        try:
            if not self.agent_executor:
                self.initialize_agent()

            result = self.agent_executor.invoke({"input": task})
            return {"status": "success", "output": result}
        except Exception as e:
            return {"status": "error", "error": str(e)}
