from pathlib import Path

import pytest

from lyrebird.skills import SkillsLibrary


@pytest.fixture
def skills() -> SkillsLibrary:
    root = Path(__file__).resolve().parent.parent / "skills"
    return SkillsLibrary(root=root)


def test_skills_library_lists_modules(skills):
    names = skills.list()
    assert "incident-probing" in names
    assert "evidence-schema" in names
    assert "mechanism-taxonomy" in names
    assert "skeptic-checklist" in names
    assert "report-authoring" in names
    assert "orchestration-playbook" in names


def test_skill_metadata_parsed(skills):
    meta = skills.metadata("incident-probing")
    assert meta.name == "incident-probing"
    assert "interview" in meta.description.lower() or "candidate" in meta.description.lower()


def test_skill_body_loaded_only_on_demand(skills):
    body = skills.load_body("incident-probing")
    assert "关键事件" in body or "critical incident" in body.lower()


def test_missing_skill_raises(skills):
    with pytest.raises(KeyError):
        skills.metadata("nope")
