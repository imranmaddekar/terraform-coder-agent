from pathlib import Path

import pytest

from agent_framework import FileSkillsSource

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"

EXPECTED_SKILLS = {"terraform-conventions", "plan-review-checklist", "brownfield-drift-review"}


@pytest.mark.asyncio
async def test_the_three_shipped_skills_are_discoverable() -> None:
    source = FileSkillsSource(str(SKILLS_DIR))
    skills = await source.get_skills(None)
    by_name = {s.frontmatter.name: s for s in skills}
    assert set(by_name) == EXPECTED_SKILLS
    for skill in by_name.values():
        assert skill.frontmatter.description, f"{skill.frontmatter.name} needs a description"


def test_skill_scripts_can_never_run() -> None:
    """The project deliberately configures no script runner: even if someone
    drops a script into a skill folder, it must not be executable."""
    from tfagent.agent import _build_skills_provider

    provider = _build_skills_provider()
    # The provider's file source carries no script runner.
    sources = [provider]
    # Walk any wrapping sources down to FileSkillsSource instances.
    seen_file_sources = []
    stack = [getattr(provider, "_source", None)]
    while stack:
        src = stack.pop()
        if src is None:
            continue
        if isinstance(src, FileSkillsSource):
            seen_file_sources.append(src)
        for attr in ("_source", "_sources", "_inner", "_inner_source", "_inner_sources"):
            inner = getattr(src, attr, None)
            if inner is None:
                continue
            stack.extend(inner if isinstance(inner, (list, tuple)) else [inner])
    assert seen_file_sources, "expected the provider to wrap a FileSkillsSource"
    assert all(fs._script_runner is None for fs in seen_file_sources)


def test_conventions_content_migrated_into_the_conventions_skill() -> None:
    text = (SKILLS_DIR / "terraform-conventions" / "SKILL.md").read_text(encoding="utf-8")
    for marker in (
        'managed-by = "terraform-coder-agent"',
        'tfagent-session-scope = "sandbox"',
        "swedencentral",
        "~> 4.0",
    ):
        assert marker in text
