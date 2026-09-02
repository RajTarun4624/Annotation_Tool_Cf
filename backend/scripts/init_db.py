"""Create the application database on the shared RDS instance if it does not exist.

Run as a one-off task before the service starts. Connects to the default
'postgres' maintenance database using the same credentials the app uses, then
issues CREATE DATABASE for the configured DB_NAME when it is missing.
"""

import os
import sys

import psycopg2
from psycopg2 import sql

DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_USER = os.environ["DB_USER"]
DB_PASS = os.environ["DB_PASS"]
DB_NAME = os.environ["DB_NAME"]


def main() -> None:
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        dbname="postgres",
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
            if cur.fetchone():
                print(f"Database '{DB_NAME}' already exists.")
                return
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
            print(f"Created database '{DB_NAME}'.")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"init_db failed: {exc}", file=sys.stderr)
        sys.exit(1)
