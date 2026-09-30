"""Explicit offline Work schema/role provisioning and scoped policy management.

Credentials come from the environment, never command-line arguments or output.
Use one shared Work authority DB for entry and all organization runtimes.
Octop databases and private volumes remain separate per institution.
"""

from __future__ import annotations

import argparse
import os

import psycopg

from octop.infra.work.control_plane import WorkControlPlane
from octop.infra.work.permissions import provision_principal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    provision = commands.add_parser("principal")
    provision.add_argument("role")
    provision.add_argument("--kind", required=True, choices=("entry", "runtime", "manager"))
    provision.add_argument("--runtime-id")
    provision.add_argument("--organization-id")
    policy = commands.add_parser("policy")
    policy.add_argument("organization")
    policy.add_argument("capability")
    policy.add_argument("--enabled", action=argparse.BooleanOptionalAction, required=True)
    policy.add_argument("--billable", action=argparse.BooleanOptionalAction, required=True)
    args = parser.parse_args()
    if args.command == "policy":
        with psycopg.connect(os.environ["WORK_MANAGER_DATABASE_URL"]) as conn:
            row = conn.execute(
                "SELECT public.work_manage_policy(%s,%s,%s,%s)",
                (args.organization, args.capability, args.enabled, args.billable),
            ).fetchone()
            print({"policy_revision": row[0] if row else None})
    else:
        url = os.environ["WORK_MIGRATION_DATABASE_URL"]
        if args.command == "migrate":
            control = WorkControlPlane(url, "migration-owner")
            control.close()
            print("Work schema migration complete")
        else:
            provision_principal(
                url,
                args.role,
                kind=args.kind,
                runtime_id=args.runtime_id,
                organization_id=args.organization_id,
            )
            print("Work principal provisioned")


if __name__ == "__main__":
    main()
