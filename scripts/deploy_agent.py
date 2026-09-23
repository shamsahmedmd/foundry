"""Deploy a new agent version to one Foundry project and route the endpoint to it.

    python scripts/deploy_agent.py --env dev --manifest release/manifest.json \
        --foundry-endpoint $FOUNDRY_PROJECT_ENDPOINT

Outputs (steps.<id>.outputs): agent_version, previous_version
"""

from __future__ import annotations

import argparse

from foundry_common import (
    DEFAULT_MANIFEST,
    append_summary,
    create_version,
    load_manifest,
    log,
    project_client,
    resolve_endpoint,
    route_traffic,
    routed_version,
    set_output,
    wait_for_active,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True, help="Environment name recorded on the version (dev/test/prod)")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--foundry-endpoint")
    parser.add_argument("--no-route", action="store_true", help="Create the version but keep traffic on the current one")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    name = manifest["agent_name"]
    client = project_client(resolve_endpoint(args.foundry_endpoint))

    previous = routed_version(client, name) or ""
    log(f"deploying {name} ({manifest['kind']}) git_sha={manifest['git_sha']} to {args.env}; current version: {previous or 'none'}")

    version = create_version(client, manifest, args.env)
    wait_for_active(client, name, version, timeout_s=args.timeout)
    if not args.no_route:
        route_traffic(client, name, version)

    set_output("agent_version", version)
    set_output("previous_version", previous)
    append_summary(f"### Deployed `{name}` v{version} to **{args.env}**\nPrevious version: `{previous or 'none'}`\n")


if __name__ == "__main__":
    main()
