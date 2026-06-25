"""Backfill geo_location for historical rows that predate ip2region resolution.

Older login_sessions / visit_events were written with geo_location='未知' (the
pre-ip2region behavior resolved every public IP to 未知). This re-resolves those
rows from their stored ip_address. Guarded: dry-run by default, commits only with
--write, and refuses to run if the ip2region xdb is unavailable.

Usage:
    python scripts/backfill_geo.py            # dry-run: report only, no writes
    python scripts/backfill_geo.py --write    # apply updates (single committed txn)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, or_, select, update

from app.core.database import SessionLocal
from app.models.login_session import LoginSession
from app.models.visit_event import VisitEvent
from app.services.geo_service import _get_searcher, resolve_ip_geo

STALE_VALUES = ("未知",)


def _stale_filter(model):
    return or_(model.geo_location.in_(STALE_VALUES), model.geo_location.is_(None))


def backfill(session, model, has_country_code: bool, apply: bool) -> int:
    total = session.scalar(select(func.count()).select_from(model))
    stale_before = session.scalar(
        select(func.count()).select_from(model).where(_stale_filter(model))
    )
    ips = [
        row[0]
        for row in session.execute(
            select(model.ip_address).where(_stale_filter(model)).distinct()
        ).all()
    ]
    print(f"\n[{model.__tablename__}] rows={total} stale(未知/NULL)={stale_before} distinct_ips={len(ips)}")

    changed_rows = 0
    sample: list[str] = []
    for ip in ips:
        geo = resolve_ip_geo(ip)
        name = geo["name"]
        if name == "未知":
            continue  # still unresolvable (e.g. "unknown" / bogus IP) — leave as-is

        values = {"geo_location": name}
        if has_country_code:
            values["country_code"] = geo["country_code"]

        where = (model.ip_address == ip, _stale_filter(model))  # multi-column guard
        if apply:
            result = session.execute(update(model).where(*where).values(**values))
            changed_rows += result.rowcount or 0
        else:
            changed_rows += session.scalar(
                select(func.count()).select_from(model).where(*where)
            ) or 0
        if len(sample) < 8:
            sample.append(f"  {ip:>16s} -> {name}")

    for line in sample:
        print(line)
    if len(ips) > len(sample):
        print(f"  ... (+{len(ips) - len(sample)} more IPs)")
    print(f"[{model.__tablename__}] {'UPDATED' if apply else 'WOULD UPDATE'} rows: {changed_rows}")
    return changed_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="apply updates (default: dry-run)")
    args = parser.parse_args()

    if _get_searcher() is None:
        print("ERROR: ip2region xdb unavailable — refusing to run "
              "(every IP would resolve to 未知, so backfill would be a no-op at best).")
        sys.exit(1)

    session = SessionLocal()
    try:
        total_changed = 0
        total_changed += backfill(session, LoginSession, has_country_code=False, apply=args.write)
        total_changed += backfill(session, VisitEvent, has_country_code=True, apply=args.write)

        if args.write:
            session.commit()
            print(f"\nCOMMITTED. {total_changed} row(s) updated.")
        else:
            session.rollback()
            print(f"\nDRY-RUN: {total_changed} row(s) would change. Re-run with --write to apply.")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
