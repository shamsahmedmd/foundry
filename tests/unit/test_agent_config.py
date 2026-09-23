import pytest

from foundry_common import REPO_ROOT, build_manifest, load_agent_config, read_instructions, version_metadata
from validate_agent_config import validate


@pytest.fixture
def config():
    return load_agent_config(REPO_ROOT / "agent.yaml")


def test_repo_agent_yaml_is_valid(config):
    assert validate(config, REPO_ROOT) == []


def test_invalid_name_rejected(config):
    config["name"] = "bad name!"
    assert any("name" in e for e in validate(config, REPO_ROOT))


def test_only_prompt_kind_allowed(config):
    config["kind"] = "hosted"
    assert validate(config, REPO_ROOT)


def test_unknown_field_rejected(config):
    config["hosted"] = {"cpu": "1"}
    assert validate(config, REPO_ROOT)


def test_function_tools_rejected(config):
    config["prompt"]["tools"] = [{"type": "function", "name": "x"}]
    assert any("function tools" in e for e in validate(config, REPO_ROOT))


def test_mcp_tool_allowed(config):
    config["prompt"]["tools"] = [{"type": "mcp", "server_label": "orders", "server_url": "https://x.example/mcp"}]
    assert validate(config, REPO_ROOT) == []


def test_secret_in_tool_rejected(config):
    config["prompt"]["tools"] = [{"type": "mcp", "headers": {"api_key": "sk_live_0123456789abcdef0123"}}]
    assert any("secret" in e for e in validate(config, REPO_ROOT))


def test_secret_in_prompt_rejected(config, tmp_path):
    (tmp_path / "p.md").write_text("Use password: SuperSecretValue123456 to log in", encoding="utf-8")
    config["instructions_file"] = "p.md"
    assert any("secret" in e for e in validate(config, tmp_path))


def test_missing_instructions_file(config):
    config["instructions_file"] = "prompts/missing.md"
    assert any("not found" in e for e in validate(config, REPO_ROOT))


def test_manifest_and_metadata(config):
    manifest = build_manifest(config, read_instructions(config), "deadbeef")
    meta = version_metadata(manifest, "dev", {"promoted_from": "dev:v1"})
    assert meta["git_sha"] == "deadbeef"
    assert meta["environment"] == "dev"
    assert meta["owner"] == "ai-platform-team"
    assert meta["promoted_from"] == "dev:v1"
    assert len(meta) <= 16 and all(len(v) <= 512 for v in meta.values())
