"""Create the immutable release manifest (agent config + prompt + prompt hash + git SHA).

    python scripts/build_manifest.py --config agent.yaml --git-sha $GITHUB_SHA

The manifest is uploaded as a workflow artefact and is the only input to every
deploy/promote step, so Dev, Test and Prod always receive exactly the same agent.
"""

from __future__ import annotations

import argparse
import os

from foundry_common import (
    DEFAULT_MANIFEST,
    REPO_ROOT,
    append_summary,
    build_manifest,
    load_agent_config,
    log,
    read_instructions,
    save_manifest,
    set_output,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(REPO_ROOT / "agent.yaml"))
    parser.add_argument("--git-sha", default=os.environ.get("GITHUB_SHA") or "local")
    parser.add_argument("--output", default=str(DEFAULT_MANIFEST))
    args = parser.parse_args()

    config = load_agent_config(args.config)
    manifest = build_manifest(config, read_instructions(config), args.git_sha)
    save_manifest(manifest, args.output)
    set_output("agent_name", manifest["agent_name"])
    append_summary(
        f"### Release manifest\n\n| Field | Value |\n|---|---|\n"
        f"| Agent | `{manifest['agent_name']}` |\n"
        f"| Model | `{config['model']}` |\n"
        f"| Git SHA | `{manifest['git_sha']}` |\n"
        f"| Prompt SHA-256 | `{manifest['instructions_sha256'][:16]}…` |\n"
    )
    log(f"wrote {args.output}")


if __name__ == "__main__":
    main()
