"""Copy trade routes from the old MineTrace database (v1 schema) into the new one.

  python migrate_legacy.py path/to/old/minetrace.db
"""

import sqlite3
import sys

from config import mineral_for_hs
from db import init_db, session, upsert_flow


def main(old_path):
    init_db()
    old = sqlite3.connect(old_path)
    old.row_factory = sqlite3.Row
    rows = old.execute("SELECT * FROM trade_routes").fetchall()
    old.close()

    moved = 0
    with session() as conn:
        for row in rows:
            mineral = mineral_for_hs(str(row["hs_code"]))
            if not mineral:
                continue
            upsert_flow(
                conn,
                mineral=mineral,
                hs_code=str(row["hs_code"]),
                year=row["year"],
                reporter_iso=row["from_iso"],
                partner_iso=row["to_iso"],
                flow="X",
                value_usd=row["trade_value"],
                net_weight_kg=row["quantity_kg"],
                is_reported=row["reported"],
            )
            moved += 1
    print(f"Copied {moved} legacy export records.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
