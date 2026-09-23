"""Delete a failing agent version. Refuses to delete the version that serves traffic.

    python scripts/delete_agent_version.py --agent-version 8 --foundry-endpoint $FOUNDRY_ENDPOINT_PROD
"""

from __future__ import annotations

import argparse

from foundry_common import fail, load_agent_config, log, project_client, resolve_endpoint, routed_version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-version", required=True)
    parser.add_argument("--foundry-endpoint")
    parser.add_argument("--config", default="agent.yaml")
    args = parser.parse_args()

    name = load_agent_config(args.config)["name"]
    client = project_client(resolve_endpoint(args.foundry_endpoint))
    if routed_version(client, name) == str(args.agent_version):
        fail(f"v{args.agent_version} is serving traffic; roll back to another version before deleting it")
    client.agents.delete_version(agent_name=name, agent_version=str(args.agent_version))
    log(f"deleted {name} v{args.agent_version}")


if __name__ == "__main__":
    main()
