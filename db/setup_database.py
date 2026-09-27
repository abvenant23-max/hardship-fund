"""One-off setup of a new, empty database (for example on Neon),
run from your own computer against its external connection string.

    python db/setup_database.py --dsn "postgresql://..."           # tables, views, sample data
    python db/setup_database.py --dsn "postgresql://..." --train   # ...then train and activate the models

With --train, set HARDSHIP_MODEL_REPO and HF_TOKEN first so the trained
models are uploaded where the deployed API can download them
(backend/ml/store.py). An existing database is left alone: only the
migrations, which are safe to re-run, are applied.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from load_data import load  # noqa: E402


def ml(dsn: str, *args: str) -> None:
    print(f"\n$ python -m backend.ml {' '.join(args)}", flush=True)
    subprocess.run([sys.executable, "-m", "backend.ml", "--dsn", dsn, *args], cwd=ROOT, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn", required=True, help="the database's external connection string")
    ap.add_argument("--train", action="store_true", help="train, activate and run the models afterwards")
    args = ap.parse_args()

    with psycopg2.connect(args.dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.households') IS NOT NULL")
        exists = cur.fetchone()[0]
    conn.close()

    if exists:
        print("The database already has the platform's tables; applying migrations only.")
        with psycopg2.connect(args.dsn) as conn, conn.cursor() as cur:
            for m in sorted((HERE / "migrations").glob("*.sql")):
                print(f"  {m.name}")
                cur.execute(m.read_text(encoding="utf-8"))
        conn.close()
    else:
        load(args.dsn)   # schema.sql + views.sql + the sample data in db/seed/

    if args.train:
        if not os.environ.get("HARDSHIP_MODEL_REPO"):
            print("\nWarning: HARDSHIP_MODEL_REPO is not set, so the models stay on this computer only "
                  "and the deployed API will keep using the rule-based placeholder.")
        stamp = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
        need, rep = f"lgbm-{stamp}", f"repeat-{stamp}"
        ml(args.dsn, "train", "--version", need)
        ml(args.dsn, "activate", need)
        ml(args.dsn, "score")
        ml(args.dsn, "train-repeat", "--version", rep)
        ml(args.dsn, "activate", rep)
        ml(args.dsn, "forecast")
        ml(args.dsn, "drift")
    print("\nDone.")


if __name__ == "__main__":
    main()
