from pathlib import Path
from unittest.mock import patch

import pytest

from tfagent.config import AZURE_OPENAI, FOUNDRY_CLAUDE, GITHUB_MODELS, Settings


def load_with_env(tmp_path: Path, **env: str) -> Settings:
    base = {"TFAGENT_WORKSPACE": str(tmp_path)}
    with patch.dict("os.environ", {**base, **env}, clear=False):
        return Settings.load()


def test_provider_defaults_to_azure_openai_when_unset_or_empty(tmp_path: Path) -> None:
    assert load_with_env(tmp_path, TFAGENT_MODEL_PROVIDER="").model_provider == AZURE_OPENAI


def test_unknown_provider_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="TFAGENT_MODEL_PROVIDER"):
        load_with_env(tmp_path, TFAGENT_MODEL_PROVIDER="not_a_real_provider")


def test_required_model_env_lists_azure_openai_vars(tmp_path: Path) -> None:
    settings = load_with_env(
        tmp_path,
        TFAGENT_MODEL_PROVIDER=AZURE_OPENAI,
        AZURE_OPENAI_ENDPOINT="https://r.openai.azure.com",
        AZURE_OPENAI_API_KEY="k",
        AZURE_OPENAI_DEPLOYMENT="gpt-4.1",
    )
    assert set(settings.required_model_env) == {
        "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT",
    }
    assert all(settings.required_model_env.values())
    assert "Azure OpenAI" in settings.model_label
    assert settings.model_endpoint_label == "https://r.openai.azure.com"


def test_required_model_env_lists_claude_foundry_vars(tmp_path: Path) -> None:
    settings = load_with_env(
        tmp_path,
        TFAGENT_MODEL_PROVIDER=FOUNDRY_CLAUDE,
        ANTHROPIC_FOUNDRY_RESOURCE="my-foundry",
        ANTHROPIC_FOUNDRY_API_KEY="k",
    )
    assert set(settings.required_model_env) == {
        "ANTHROPIC_FOUNDRY_RESOURCE", "ANTHROPIC_FOUNDRY_API_KEY",
    }
    assert all(settings.required_model_env.values())
    assert "Claude on Foundry" in settings.model_label
    assert settings.model_endpoint_label == "https://my-foundry.services.ai.azure.com/anthropic"


def test_required_model_env_lists_only_github_token(tmp_path: Path) -> None:
    settings = load_with_env(
        tmp_path,
        TFAGENT_MODEL_PROVIDER=GITHUB_MODELS,
        GITHUB_TOKEN="gh-token",
    )
    assert set(settings.required_model_env) == {"GITHUB_TOKEN"}
    assert all(settings.required_model_env.values())
    assert settings.github_model == "openai/gpt-4.1"
    assert settings.github_endpoint == "https://models.github.ai/inference"
    assert "GitHub Models" in settings.model_label
    assert settings.model_endpoint_label == "https://models.github.ai/inference"


def test_claude_endpoint_label_is_empty_until_resource_is_set(tmp_path: Path) -> None:
    settings = load_with_env(
        tmp_path,
        TFAGENT_MODEL_PROVIDER=FOUNDRY_CLAUDE,
        ANTHROPIC_FOUNDRY_RESOURCE="",
        ANTHROPIC_FOUNDRY_API_KEY="",
    )
    assert settings.model_endpoint_label == ""
