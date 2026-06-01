"""Offline agent tests — verify wiring (prompt assembly, schema linkage) without network."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lyrebird.agents.base import AgentContext, BaseAgent
from lyrebird.agents import (
    intake, interviewer, evidence_mapper,
    mechanism_modeler, skeptic, report_composer, simulated_candidate,
)
from lyrebird.llm.client import LLMClient, Role
from lyrebird.skills import SkillsLibrary
from lyrebird.schemas import CandidateProfile, CoreExperience, Hypothesis, Priority


@pytest.fixture
def ctx():
    skills = SkillsLibrary(root=Path(__file__).resolve().parent.parent / "skills")
    llm = LLMClient(_sdk=MagicMock())
    return AgentContext(llm=llm, skills=skills, run_id="test")


def test_intake_agent_factory(ctx):
    agent = intake.make_intake_agent()
    assert agent.name == "intake"
    assert agent.role == Role.STANDARD
    prompt = agent.build_system_prompt(ctx)
    assert "假设生成专家" in prompt
    assert "output_contract" in prompt.lower()


def test_interviewer_loads_incident_probing_skill(ctx):
    agent = interviewer.make_interviewer_agent()
    prompt = agent.build_system_prompt(ctx)
    assert "incident-probing" in prompt
    assert "关键事件追问法" in prompt


def test_evidence_mapper_loads_evidence_schema_skill(ctx):
    agent = evidence_mapper.make_evidence_mapper()
    prompt = agent.build_system_prompt(ctx)
    assert "evidence-schema" in prompt


def test_mechanism_modeler_uses_heavy_role(ctx):
    agent = mechanism_modeler.make_mechanism_modeler()
    assert agent.role == Role.HEAVY
    prompt = agent.build_system_prompt(ctx)
    assert "mechanism-taxonomy" in prompt


def test_skeptic_loads_checklist(ctx):
    agent = skeptic.make_skeptic()
    prompt = agent.build_system_prompt(ctx)
    assert "skeptic-checklist" in prompt


def test_report_composer_uses_heavy_role(ctx):
    agent = report_composer.make_report_composer()
    assert agent.role == Role.HEAVY
    prompt = agent.build_system_prompt(ctx)
    assert "report-authoring" in prompt


def test_simulated_candidate_no_skill(ctx):
    agent = simulated_candidate.make_simulated_candidate()
    assert agent.skill_names == []
    prompt = agent.build_system_prompt(ctx)
    assert "候选人" in prompt
