"""Skill loader for agent prose skills.

Each skill is a markdown file under ``backend/skills/<name>/SKILL.md``.
The loader reads the file and returns its contents as a string so the
LLM client can inject it as a system prompt.
"""

from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parent

_VALID_SKILLS = {
    "fa_impact_narrative",
    "de_remediation_explanation",
    "dq_validation_summary",
    "controller_triage_note",
}


def load_skill(name: str) -> str:
    """Load a skill's SKILL.md content by name.

    Args:
        name: One of ``fa_impact_narrative``, ``de_remediation_explanation``,
            ``dq_validation_summary``, ``controller_triage_note``.

    Returns:
        The full text of the SKILL.md file.

    Raises:
        ValueError: If the skill name is not recognised.
        FileNotFoundError: If the skill file does not exist on disk.
    """
    if name not in _VALID_SKILLS:
        raise ValueError(
            f"Unknown skill: {name!r}. Valid skills: {sorted(_VALID_SKILLS)}"
        )
    path = _SKILLS_DIR / name / "SKILL.md"
    return path.read_text(encoding="utf-8")
