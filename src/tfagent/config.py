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
            # The canonical workflow (instructions.py) is fmt/init/validate/plan/
            # apply per todo, plus a re-plan/re-apply cycle on any validate or
            # apply failure. 8 was too tight for a multi-todo task with even one
            # retry; 20 gives that room while still bounding runaway loops.
            max_iterations=_env_int("TFAGENT_MAX_ITERATIONS", 20),
            tf_timeout_seconds=_env_int("TFAGENT_TF_TIMEOUT_SECONDS", 600),
        )


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"Environment variable {name}={raw!r} is not a valid integer.") from None
