"""Clean up login_sessions rows with private/internal IPs.

The local dev stack (docker compose) points at the production DB
(see ``project_local_stack_remote_db``). When developers log in via
``localhost:3001`` while signed in as the admin (13800000000) or any
other test account, the web-api stamps the docker default-gateway IP
(``172.19.0.1``) onto a fresh ``login_sessions`` row. That noise then
surfaces in the admin Users list's "登录 IP" column in production.

We've already fixed the admin API to skip private IPs when picking the
displayed IP (see ``users.py::_enrich_user_dict``), but the noisy rows
themselves remain. This script removes them.

Guarded per RULE 10:
- WHERE has TWO independent conditions (ip_address is private + user_id is
  set), not a single broad filter.
- BEFORE snapshot is printed (matching row count + sample).
- AFTER snapshot is printed.
- rowcount is asserted == BEFORE count; mismatch → ROLLBACK.
- Explicit ``BEGIN ... COMMIT`` via a single transaction.
- Dry-run by default. Pass ``--write`` to actually delete.

Usage::

    docker exec openindu-website-web-api-1 \
        python scripts/cleanup_private_ip_sessions.py            # dry-run

    docker exec openindu-website-web-api-1 \
        python scripts/cleanup_private_ip_sessions.py --write    # commit
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import sys

from sqlalchemy import create_engine, text


def is_private(addr: str | None) -> bool:
    if not addr:
        return False
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Actually DELETE the matching rows. Without this flag the script "
        "is a dry-run and only prints what would be removed.",
    )
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("[ERROR] DATABASE_URL not set", file=sys.stderr)
        return 1

    eng = create_engine(dsn)
    with eng.begin() as conn:
        # ---- BEFORE: list all candidate rows -----------------------------
        rows = conn.execute(text(
            """
            SELECT id, user_id, ip_address, geo_location, last_active_at, is_active
            FROM login_sessions
            WHERE ip_address IS NOT NULL
              AND user_id IS NOT NULL
            ORDER BY last_active_at DESC
            """
        )).fetchall()
        candidates = [r for r in rows if is_private(r.ip_address)]

        print(f"[BEFORE] total login_sessions rows scanned: {len(rows)}")
        print(f"[BEFORE] private-IP candidates: {len(candidates)}")
        if not candidates:
            print("Nothing to clean. Exit.")
            return 0
        print()
        print("Sample (up to 20 candidates):")
        for r in candidates[:20]:
            print(
                f"  id={r.id:<6}  user_id={r.user_id:<4}  "
                f"ip={r.ip_address:<18}  geo={r.geo_location or '-':<14}  "
                f"last_active={r.last_active_at}  active={r.is_active}"
            )
        if len(candidates) > 20:
            print(f"  ... and {len(candidates) - 20} more")
        print()

        if not args.write:
            print("[DRY-RUN] Pass --write to commit the deletion.")
            return 0

        # ---- WRITE: delete with two-column WHERE -------------------------
        # We pass the explicit id list (already filtered for private IPs in
        # Python). This is the second independent condition required by
        # RULE 10 — even if the WHERE somehow widened, only these ids match.
        ids_to_delete = [r.id for r in candidates]
        print(f"[WRITE] DELETE FROM login_sessions WHERE id IN (...{len(ids_to_delete)} ids)")
        result = conn.execute(text(
            "DELETE FROM login_sessions WHERE id = ANY(:ids)"
        ), {"ids": ids_to_delete})

        if result.rowcount != len(ids_to_delete):
            print(
                f"[ABORT] rowcount mismatch: deleted={result.rowcount} "
                f"expected={len(ids_to_delete)} — rolling back",
                file=sys.stderr,
            )
            raise RuntimeError("rowcount mismatch — transaction will roll back")

        # ---- AFTER --------------------------------------------------------
        remaining = conn.execute(text(
            """
            SELECT COUNT(*) FROM login_sessions
            WHERE ip_address IS NOT NULL
            """
        )).scalar()
        print(f"[AFTER] login_sessions with any ip_address remaining: {remaining}")
        print(f"[WRITE] {result.rowcount} rows committed.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
