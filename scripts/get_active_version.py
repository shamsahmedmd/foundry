"""Print the agent version currently served by an environment's endpoint.

    python scripts/get_active_version.py --env prod --foundry-endpoint $FOUNDRY_ENDPOINT_PROD
"""

from __future__ import annotations

import argparse

from foundry_common import fail, load_agent_config, project_client, resolve_endpoint, routed_version, set_output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default="", help="Only used for log output")
    parser.add_argument("--foundry-endpoint")
    parser.add_argument("--config", default="agent.yaml")
    parser.add_argument("--agent-name")
    args = parser.parse_args()

    name = args.agent_name or load_agent_config(args.config)["name"]
    version = routed_version(project_client(resolve_endpoint(args.foundry_endpoint)), name)
    if version is None:
        fail(f"agent {name} not found in {args.env or 'project'}")
    set_output("active_version", version)


if __name__ == "__main__":
    main()
