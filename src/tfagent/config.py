"""Central configuration, loaded from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    # GitHub Models (OpenAI-compatible endpoint)
    github_token: str
    github_model: str
    github_endpoint: str

    # Runtime
    workspace: Path
    max_iterations: int
    tf_timeout_seconds: int

    @staticmethod
    def load() -> "Settings":
        workspace = Path(os.getenv("TFAGENT_WORKSPACE", "./workspace")).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        return Settings(
            github_token=os.getenv("GITHUB_TOKEN", ""),
            github_model=os.getenv("GITHUB_MODEL", "openai/gpt-4.1"),
            github_endpoint=os.getenv("GITHUB_MODELS_ENDPOINT", "https://models.github.ai/inference"),
            workspace=workspace,
            max_iterations=int(os.getenv("TFAGENT_MAX_ITERATIONS", "8")),
            tf_timeout_seconds=int(os.getenv("TFAGENT_TF_TIMEOUT_SECONDS", "600")),
        )
