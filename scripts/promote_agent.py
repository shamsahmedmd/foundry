"""Promote an agent version between environments, or roll back within one.

Promotion (different environments, separate Foundry projects):
    python scripts/promote_agent.py --from-env dev --to-env test \
        --agent-version 7 --source-endpoint $FOUNDRY_ENDPOINT_DEV \
        --foundry-endpoint $FOUNDRY_ENDPOINT_TEST --manifest release/manifest.json

  1. Verifies the source version exists and was built from the same manifest
     (git SHA + instructions hash), so only evaluated releases move forward.
  2. Creates the identical version in the target project and waits until active.
  3. Routes the target endpoint to it (skip with --no-route).

Rollback (same environment):
    python scripts/promote_agent.py --from-env prod --to-env prod \
        --agent-version 5 --foundry-endpoint $FOUNDRY_ENDPOINT_PROD

  Re-points the endpoint at an existing known-good version. No redeployment.
"""

from __future__ import annotations

import argparse

from foundry_common import (
    DEFAULT_MANIFEST,
    append_summary,
    create_version,
    fail,
    load_agent_config,
    load_manifest,
    log,
    project_client,
    resolve_endpoint,
    route_traffic,
    routed_version,
    set_output,
    version_info,
    version_meta,
    wait_for_active,
)


def verify_source(manifest: dict, meta: dict[str, str]) -> None:
    mismatches = [
        f"{key}: source={meta.get(key)!r} manifest={expected!r}"
        for key, expected in (
            ("git_sha", manifest["git_sha"]),
            ("instructions_sha256", manifest["instructions_sha256"]),
        )
        if expected and meta.get(key) != expected
    ]
    if mismatches:
        fail("Source version does not match the release manifest: " + "; ".join(mismatches))


def rollback(args) -> None:
    config = load_agent_config(args.config)
    name = args.agent_name or config["name"]
    client = project_client(resolve_endpoint(args.foundry_endpoint))
    current = routed_version(client, name)
    version_info(client, name, args.agent_version)  # raises if the version doesn't exist
    wait_for_active(client, name, args.agent_version, timeout_s=args.timeout)
    route_traffic(client, name, args.agent_version)
    set_output("agent_version", args.agent_version)
    set_output("previous_version", current or "")
    append_summary(f"### Rolled back `{name}` in **{args.to_env}**: v{current} -> v{args.agent_version}\n")


def promote(args) -> None:
    manifest = load_manifest(args.manifest)
    name = manifest["agent_name"]

    if args.source_endpoint:
        source = project_client(args.source_endpoint)
        verify_source(manifest, version_meta(source, name, args.agent_version))
        log(f"source {args.from_env} v{args.agent_version} matches manifest git_sha={manifest['git_sha']}")
    else:
        log("WARNING: --source-endpoint not given; skipping source version verification")

    target = project_client(resolve_endpoint(args.foundry_endpoint))
    previous = routed_version(target, name) or ""
    version = create_version(
        target,
        manifest,
        args.to_env,
        {"promoted_from": f"{args.from_env}:v{args.agent_version}"},
    )
    wait_for_active(target, name, version, timeout_s=args.timeout)
    if not args.no_route:
        route_traffic(target, name, version)

    set_output("agent_version", version)
    set_output("previous_version", previous)
    append_summary(
        f"### Promoted `{name}` {args.from_env} v{args.agent_version} -> **{args.to_env}** v{version}\n"
        f"Previous {args.to_env} version (rollback target): `{previous or 'none'}`\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-env", required=True)
    parser.add_argument("--to-env", required=True)
    parser.add_argument("--agent-version", required=True, help="Version in the source environment")
    parser.add_argument("--foundry-endpoint", help="Target project endpoint")
    parser.add_argument("--source-endpoint", help="Source project endpoint (enables provenance check)")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--config", default="agent.yaml", help="Used for rollback when no manifest is available")
    parser.add_argument("--agent-name")
    parser.add_argument("--no-route", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    if args.from_env == args.to_env:
        rollback(args)
    else:
        promote(args)


if __name__ == "__main__":
    main()
