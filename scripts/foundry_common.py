"""Shared helpers for the CI/CD scripts.

All scripts authenticate with DefaultAzureCredential. In GitHub Actions the workflow
logs in with OIDC workload identity federation first (azure/login), so no secret is
ever stored in the repository or the pipeline.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AGENT_CONFIG = REPO_ROOT / "agent.yaml"
DEFAULT_MANIFEST = REPO_ROOT / "release" / "manifest.json"
METADATA_MAX_LEN = 512

# Windows consoles default to a legacy code page; reports use Unicode symbols.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- config

def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def load_agent_config(path: str | Path = DEFAULT_AGENT_CONFIG) -> dict[str, Any]:
    return load_yaml(path)


def read_instructions(config: dict[str, Any], base_dir: Path = REPO_ROOT) -> str:
    return (base_dir / config["instructions_file"]).read_text(encoding="utf-8")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_endpoint(value: str | None) -> str:
    endpoint = value or os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        fail("Foundry project endpoint missing: pass --foundry-endpoint or set FOUNDRY_PROJECT_ENDPOINT")
    return endpoint


# --------------------------------------------------------------------------- manifest

def build_manifest(config: dict[str, Any], instructions: str, git_sha: str) -> dict[str, Any]:
    """The immutable release artefact that is promoted between environments."""
    return {
        "schema_version": 1,
        "agent_name": config["name"],
        "kind": config["kind"],
        "git_sha": git_sha,
        "instructions_sha256": sha256_text(instructions),
        "instructions": instructions,
        "config": config,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def save_manifest(manifest: dict[str, Any], path: str | Path = DEFAULT_MANIFEST) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if sha256_text(manifest["instructions"]) != manifest["instructions_sha256"]:
        fail(f"Manifest {path} has been tampered with: instructions hash mismatch")
    return manifest


def version_metadata(manifest: dict[str, Any], environment: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    meta = {
        "git_sha": manifest["git_sha"],
        "environment": environment,
        "instructions_sha256": manifest["instructions_sha256"],
        "pipeline_run": os.environ.get("GITHUB_RUN_ID") or "local",
    }
    meta.update(manifest["config"].get("metadata") or {})
    meta.update(extra or {})
    return {k: str(v)[:METADATA_MAX_LEN] for k, v in meta.items()}


# --------------------------------------------------------------------------- Foundry

def project_client(endpoint: str):
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    return AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())


def build_definition(manifest: dict[str, Any]):
    """Turn a release manifest into an azure-ai-projects prompt agent definition."""
    from azure.ai.projects.models import PromptAgentDefinition

    config = manifest["config"]
    prompt = config.get("prompt") or {}
    kwargs: dict[str, Any] = {"model": config["model"], "instructions": manifest["instructions"]}
    if prompt.get("temperature") is not None:
        kwargs["temperature"] = prompt["temperature"]
    if prompt.get("tools"):
        kwargs["tools"] = prompt["tools"]
    return PromptAgentDefinition(**kwargs)


def _field(obj: Any, name: str) -> Any:
    """Read a field from an SDK model that may behave as an object or a mapping."""
    if obj is None:
        return None
    value = getattr(obj, name, None)
    if value is None and hasattr(obj, "get"):
        value = obj.get(name)
    return value


def create_version(client, manifest: dict[str, Any], environment: str, extra_metadata: dict[str, str] | None = None) -> str:
    version = client.agents.create_version(
        agent_name=manifest["agent_name"],
        definition=build_definition(manifest),
        description=(manifest["config"].get("description") or "")[:METADATA_MAX_LEN],
        metadata=version_metadata(manifest, environment, extra_metadata),
    )
    return str(_field(version, "version"))


def wait_for_active(client, agent_name: str, agent_version: str, timeout_s: int = 300, poll_s: int = 5) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        info = client.agents.get_version(agent_name=agent_name, agent_version=agent_version)
        status = _field(info, "status")
        log(f"agent={agent_name} version={agent_version} status={status}")
        # Prompt agents are usually usable immediately and may not report a status.
        if status in (None, "active"):
            return
        if status == "failed":
            fail(f"Version {agent_version} failed: {_field(info, 'error')}")
        if time.monotonic() > deadline:
            fail(f"Timed out after {timeout_s}s waiting for version {agent_version} to become active")
        time.sleep(poll_s)


def route_traffic(client, agent_name: str, agent_version: str) -> None:
    """Point 100% of the agent endpoint at one version (promotion and rollback)."""
    from azure.ai.projects import models as m

    client.agents.update_details(
        agent_name=agent_name,
        agent_endpoint=m.AgentEndpointConfig(
            version_selector=m.VersionSelector(
                version_selection_rules=[
                    m.FixedRatioVersionSelectionRule(agent_version=str(agent_version), traffic_percentage=100)
                ]
            ),
            protocol_configuration=m.ProtocolConfiguration(responses=m.ResponsesProtocolConfiguration()),
        ),
    )
    log(f"endpoint for {agent_name} now routes 100% of traffic to version {agent_version}")


def routed_version(client, agent_name: str) -> str | None:
    """Version currently served by the agent endpoint (None if the agent doesn't exist)."""
    from azure.core.exceptions import ResourceNotFoundError

    try:
        agent = client.agents.get(agent_name=agent_name)
    except ResourceNotFoundError:
        return None
    selector = _field(_field(agent, "agent_endpoint"), "version_selector")
    rules = _field(selector, "version_selection_rules") or []
    for rule in rules:
        version = _field(rule, "agent_version")
        if version:
            return str(version)
    latest = _field(_field(agent, "versions"), "latest")
    version = _field(latest, "version")
    return str(version) if version else None


def version_info(client, agent_name: str, agent_version: str):
    return client.agents.get_version(agent_name=agent_name, agent_version=agent_version)


def version_meta(client, agent_name: str, agent_version: str) -> dict[str, str]:
    return dict(_field(version_info(client, agent_name, agent_version), "metadata") or {})


# --------------------------------------------------------------------------- GitHub Actions I/O

def set_output(name: str, value: str) -> None:
    """Expose a value to later steps/jobs (steps.<id>.outputs.<name>)."""
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")
    print(f"{name}={value}")


def append_summary(markdown: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(markdown + "\n")


def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr, flush=True)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::error::{message}", flush=True)
    sys.exit(1)
