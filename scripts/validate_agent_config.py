"""Static validation of agent.yaml: JSON schema + rules the schema can't express.

    python scripts/validate_agent_config.py --config agent.yaml
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import jsonschema

from foundry_common import REPO_ROOT, fail, load_agent_config, log

SCHEMA_PATH = REPO_ROOT / "schemas" / "agent.schema.json"
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|password|token)['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9/+_\-]{16,}"),
    re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
]
MAX_INSTRUCTIONS_CHARS = 32_000


def _secret_findings(text: str, where: str) -> list[str]:
    return [f"{where} contains something that looks like a secret ({p.pattern[:30]}...)" for p in SECRET_PATTERNS if p.search(text)]


def validate(config: dict, base_dir: Path) -> list[str]:
    errors: list[str] = []
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(config), key=lambda e: list(e.path)):
        location = "/".join(str(p) for p in err.path) or "<root>"
        errors.append(f"schema: {location}: {err.message}")
    if errors:
        return errors

    instructions_path = base_dir / config["instructions_file"]
    if not instructions_path.is_file():
        errors.append(f"instructions_file not found: {config['instructions_file']}")
    else:
        text = instructions_path.read_text(encoding="utf-8")
        if not text.strip():
            errors.append("instructions_file is empty")
        if len(text) > MAX_INSTRUCTIONS_CHARS:
            errors.append(f"instructions_file is {len(text)} chars; keep it under {MAX_INSTRUCTIONS_CHARS}")
        errors += _secret_findings(text, "instructions_file")

    for i, tool in enumerate((config.get("prompt") or {}).get("tools") or []):
        if tool.get("type") == "function":
            errors.append(f"prompt.tools[{i}]: function tools need client-side execution and can't run in a prompt agent")
        errors += _secret_findings(json.dumps(tool), f"prompt.tools[{i}]")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(REPO_ROOT / "agent.yaml"))
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    config = load_agent_config(config_path)
    errors = validate(config, config_path.parent)
    if errors:
        for e in errors:
            print(f"INVALID: {e}")
        fail(f"{len(errors)} problem(s) in {args.config}")
    log(f"{args.config} is valid (agent={config['name']}, model={config['model']})")


if __name__ == "__main__":
    main()
