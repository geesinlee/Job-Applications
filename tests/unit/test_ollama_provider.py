"""Unit tests for Job-Applications OllamaProvider."""
import json
import os
from unittest.mock import MagicMock, patch

from src.llm_provider import OllamaProvider, get_llm_provider


def test_get_llm_provider_returns_ollama(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    provider = get_llm_provider()
    assert isinstance(provider, OllamaProvider)


def test_ollama_provider_generate_text():
    provider = OllamaProvider()
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"message": {"content": "Python, Kubernetes"}}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = provider.generate_text("Extract skills")
        assert res == "Python, Kubernetes"
