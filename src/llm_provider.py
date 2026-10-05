import json
import logging
import os
import urllib.request
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    def generate_text(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 2000,
    ) -> str:
        """Generate text from a prompt."""
        raise NotImplementedError


class AnthropicProvider(LLMProvider):
    """LLM provider for Anthropic Claude."""

    def __init__(self):
        try:
            import anthropic

            self.client = anthropic.Anthropic()
        except ImportError as exc:
            raise ImportError(
                "anthropic package is not installed. Run `pip install anthropic`."
            ) from exc

    def generate_text(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 2000,
    ) -> str:
        model = model or os.getenv("EVIDENCE_LLM_MODEL", "claude-haiku-4-5-20251001")
        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as exc:
            logger.error("Anthropic API error: %s", exc)
            raise


class GeminiProvider(LLMProvider):
    """LLM provider for Google Gemini."""

    def __init__(self):
        try:
            from google import genai

            # API key is automatically picked up from GEMINI_API_KEY environment variable
            self.client = genai.Client()
        except ImportError as exc:
            raise ImportError(
                "google-genai package is not installed. Run `pip install google-genai`."
            ) from exc

    def generate_text(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 2000,
    ) -> str:
        model = model or os.getenv("EVIDENCE_LLM_MODEL", "gemini-3.6-flash")
        try:
            from google.genai import types

            # Use generate_content for gemini models
            response = self.client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=max_tokens,
                    response_mime_type="application/json",
                ),
            )
            return response.text
        except Exception as exc:
            logger.error("Gemini API error: %s", exc)
            raise


class OllamaProvider(LLMProvider):
    """LLM provider for local Ollama (chat API)."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (
            base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        ).rstrip("/")

    def generate_text(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 2000,
    ) -> str:
        model = model or os.getenv("OLLAMA_MODEL", "llama3.2")
        payload = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"num_predict": max_tokens},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                data = json.loads(response.read())
            return data["message"]["content"]
        except Exception as exc:
            logger.error("Ollama API error: %s", exc)
            raise


class MockProvider(LLMProvider):
    """Mock provider for local testing without API keys."""

    def generate_text(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 2000,
    ) -> str:
        logger.warning("Using MockProvider (requested model: %s)", model)
        # Simple JSON fallback
        if "analyze the following job description" in prompt.lower():
            return '''
{
  "explicit_skills": ["Python", "System Design", "Kubernetes"],
  "inferred_skills": ["Distributed Systems", "Microservices"],
  "critical_criteria": ["5+ years experience", "scalable systems"],
  "nice_to_have_criteria": ["Docker", "monitoring", "documentation"],
  "importance_ranking": {
    "Python": 0.9,
    "System Design": 0.85,
    "Kubernetes": 0.8,
    "Distributed Systems": 0.75
  }
}'''
        else:
            return '''
[
  {
    "achievement": "Mock achievement",
    "context": "Mock context",
    "impact": "Mock impact",
    "skills_demonstrated": ["Python", "System Design"]
  }
]'''


def get_llm_provider() -> LLMProvider:
    """Factory method to get the configured LLM provider."""
    provider_name = os.getenv("LLM_PROVIDER", "mock").lower()

    if provider_name == "gemini":
        return GeminiProvider()
    if provider_name == "anthropic":
        return AnthropicProvider()
    if provider_name == "ollama":
        return OllamaProvider()
    return MockProvider()
