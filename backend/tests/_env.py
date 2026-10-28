"""Gives every test script its own throwaway database so tests never touch real data.

Needs DATABASE_URL to point at a Postgres server where the user may create databases. The tests use
a database named unsubvault_test on that same server and drop it first."""
import os, subprocess
import psycopg2

TEST_DB = "unsubvault_test"

def setup() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    base = url.rsplit("/", 1)[0]
    conn = psycopg2.connect(base + "/postgres")
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        cur.execute(f"CREATE DATABASE {TEST_DB}")
    conn.close()
    os.environ["DATABASE_URL"] = f"{base}/{TEST_DB}"
    r = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True)
    if r.returncode != 0:  # show WHY (a dependency upgrade that breaks migrations looks like a bare crash otherwise)
        print((r.stdout + r.stderr)[-2500:])
        raise SystemExit("alembic upgrade head failed")

def teardown() -> None:
    """Drop the throwaway database (called by run_all after the last test)."""
    url = os.environ.get("DATABASE_URL", "")
    base = url.rsplit("/", 1)[0]
    try:
        conn = psycopg2.connect(base + "/postgres")
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        conn.close()
    except Exception:
        pass
