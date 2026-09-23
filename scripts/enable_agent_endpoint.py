"""Enable (or disable) an agent endpoint, optionally pinning it to a version.

    python scripts/enable_agent_endpoint.py --agent-version 7 --foundry-endpoint $FOUNDRY_ENDPOINT_PROD
    python scripts/enable_agent_endpoint.py --disable --foundry-endpoint $FOUNDRY_ENDPOINT_PROD   # kill switch
"""

from __future__ import annotations

import argparse

from foundry_common import (
    append_summary,
    load_agent_config,
    log,
    project_client,
    resolve_endpoint,
    route_traffic,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-version")
    parser.add_argument("--foundry-endpoint")
    parser.add_argument("--config", default="agent.yaml")
    parser.add_argument("--disable", action="store_true", help="Take the endpoint offline (reversible)")
    args = parser.parse_args()

    config = load_agent_config(args.config)
    name = config["name"]
    client = project_client(resolve_endpoint(args.foundry_endpoint))

    if args.disable:
        client.agents.disable(agent_name=name)
        log(f"endpoint for {name} disabled")
        append_summary(f"### Endpoint for `{name}` **disabled**\n")
        return

    if args.agent_version:
        route_traffic(client, name, args.agent_version)
    client.agents.enable(agent_name=name)
    log(f"endpoint for {name} enabled")
    append_summary(f"### Endpoint for `{name}` enabled (version {args.agent_version or 'unchanged'})\n")


if __name__ == "__main__":
    main()
