"""Checks that manifests map onto the azure-ai-projects SDK models correctly."""

import pytest

from foundry_common import REPO_ROOT, build_definition, build_manifest, load_agent_config, read_instructions

pytest.importorskip("azure.ai.projects")


@pytest.fixture
def config():
    return load_agent_config(REPO_ROOT / "agent.yaml")


def test_prompt_definition(config):
    d = build_definition(build_manifest(config, read_instructions(config), "sha")).as_dict()
    assert d["kind"] == "prompt"
    assert d["model"] == "gpt-4.1-mini"
    assert d["temperature"] == 0.2
    assert "Contoso" in d["instructions"]
    assert "tools" not in d


def test_prompt_definition_with_tools(config):
    config["prompt"]["tools"] = [{"type": "mcp", "server_label": "orders", "server_url": "https://x.example/mcp"}]
    d = build_definition(build_manifest(config, "x", "sha")).as_dict()
    assert d["tools"][0]["server_label"] == "orders"
