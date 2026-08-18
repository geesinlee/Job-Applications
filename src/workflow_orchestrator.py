"""LangChain workflow orchestrator for Gate 10 interactive evidence discovery."""

from typing import Any, Optional
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
import os


class WorkflowOrchestrator:
    """Orchestrates job application workflow using LangChain ReAct agent."""

    def __init__(self, model: str = "gemini-flash-latest"):
        """
        Initialize orchestrator with LLM and empty tools list.

        Args:
            model: Google Generative AI model name
        """
        self.model_name = model
        self.llm = ChatGoogleGenerativeAI(
            model=model,
            temperature=0,  # Deterministic
            api_key=os.getenv("GOOGLE_API_KEY")
        )
        self.tools = []
        self.agent_executor = None

    def register_tool(self, tool: StructuredTool) -> None:
        """Register a tool with the orchestrator."""
        self.tools.append(tool)

    def initialize_agent(self) -> None:
        """Create and initialize the ReAct agent with registered tools."""
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

    def run_workflow(self, task: str):
        """Execute a workflow step and return results."""
        if not self.agent_executor:
            self.initialize_agent()

        result = self.agent_executor.invoke({"input": task})
        return result
