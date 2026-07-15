"""Central configuration, loaded from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Model providers (Microsoft Agent Framework chat clients, API-key auth).
AZURE_OPENAI = "azure_openai"      # Azure OpenAI / Foundry-hosted GPT deployment
FOUNDRY_CLAUDE = "foundry_claude"  # Anthropic Claude deployed in Azure AI Foundry
MODEL_PROVIDERS = (AZURE_OPENAI, FOUNDRY_CLAUDE)


@dataclass(frozen=True)
class Settings:
    # Which Foundry-hosted model family serves the agent.
    model_provider: str

    # Azure OpenAI / Foundry GPT deployment (model_provider=azure_openai)
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_deployment: str
    azure_openai_api_version: str

    # Claude in Foundry (model_provider=foundry_claude)
    anthropic_foundry_resource: str
    anthropic_foundry_api_key: str
    anthropic_model: str

    # Runtime
    workspace: Path
    max_iterations: int
    tf_timeout_seconds: int

    # Pipeline hand-off (export_to_repo). export_repo None => bundle fallback.
    export_repo: Path | None = None
    export_subdir: str = "terraform"

    @property
    def model_label(self) -> str:
        """Human-readable 'what model am I talking to' string."""
        if self.model_provider == AZURE_OPENAI:
            return f"{self.azure_openai_deployment or '(no deployment set)'} (Azure OpenAI)"
        return f"{self.anthropic_model} (Claude on Foundry)"

    @property
    def model_endpoint_label(self) -> str:
        if self.model_provider == AZURE_OPENAI:
            return self.azure_openai_endpoint
        if not self.anthropic_foundry_resource:
            return ""
        return f"https://{self.anthropic_foundry_resource}.services.ai.azure.com/anthropic"

    @property
    def required_model_env(self) -> dict[str, str]:
        """Env-var name -> current value for the active provider.

        Single source of truth for both the startup preflight and --check, so
        the two lists cannot drift apart.
        """
        if self.model_provider == AZURE_OPENAI:
            return {
                "AZURE_OPENAI_ENDPOINT": self.azure_openai_endpoint,
                "AZURE_OPENAI_API_KEY": self.azure_openai_api_key,
                "AZURE_OPENAI_DEPLOYMENT": self.azure_openai_deployment,
            }
        return {
            "ANTHROPIC_FOUNDRY_RESOURCE": self.anthropic_foundry_resource,
            "ANTHROPIC_FOUNDRY_API_KEY": self.anthropic_foundry_api_key,
        }

    @staticmethod
    def load() -> "Settings":
        workspace = Path(os.getenv("TFAGENT_WORKSPACE", "./workspace")).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        provider = (os.getenv("TFAGENT_MODEL_PROVIDER") or AZURE_OPENAI).strip().lower()
        if provider not in MODEL_PROVIDERS:
            raise ValueError(
                f"TFAGENT_MODEL_PROVIDER={provider!r} is not supported; "
                f"expected one of {', '.join(MODEL_PROVIDERS)}."
            )
        export_repo_raw = os.getenv("TFAGENT_EXPORT_REPO", "")
        return Settings(
            model_provider=provider,
            azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
            azure_openai_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", ""),
            azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            anthropic_foundry_resource=os.getenv("ANTHROPIC_FOUNDRY_RESOURCE", ""),
            anthropic_foundry_api_key=os.getenv("ANTHROPIC_FOUNDRY_API_KEY", ""),
            anthropic_model=os.getenv("ANTHROPIC_CHAT_MODEL", "claude-sonnet-4-5"),
            workspace=workspace,
            # The canonical workflow (instructions.py) is fmt/init/validate/plan/
            # apply per todo, plus a re-plan/re-apply cycle on any validate or
            # apply failure. 8 was too tight for a multi-todo task with even one
            # retry; 20 gives that room while still bounding runaway loops.
            max_iterations=_env_int("TFAGENT_MAX_ITERATIONS", 20),
            tf_timeout_seconds=_env_int("TFAGENT_TF_TIMEOUT_SECONDS", 600),
            export_repo=Path(export_repo_raw).resolve() if export_repo_raw else None,
            export_subdir=os.getenv("TFAGENT_EXPORT_SUBDIR", "terraform"),
        )


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"Environment variable {name}={raw!r} is not a valid integer.") from None
