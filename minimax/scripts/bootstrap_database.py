"""Initialize an isolated Compose seekdb with a scoped application account."""

import argparse
import os
from pathlib import Path
import re
import time

import pymysql

from sdd_context.config import read_env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    values = read_env(args.env_file)
    values.update({k: v for k, v in os.environ.items() if k.startswith("SEEKDB_")})
    for key in ("SEEKDB_ROOT_PASSWORD", "SEEKDB_PASSWORD"):
        if not values.get(key):
            raise SystemExit(f"Set {key} locally before bootstrapping")
    database = values.get("SEEKDB_DATABASE", "minimax_sdd")
    user = values.get("SEEKDB_USER", "minimax_app")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", database) or not re.fullmatch(r"[A-Za-z0-9_]{1,32}", user):
        raise SystemExit("Use simple alphanumeric database and account names")
    connection = None
    for _ in range(60):
        try:
            connection = pymysql.connect(host=values.get("SEEKDB_HOST", "127.0.0.1"),
                                         port=int(values.get("SEEKDB_PORT", "2881")), user="root",
                                         password=values["SEEKDB_ROOT_PASSWORD"], autocommit=True,
                                         connect_timeout=3)
            break
        except pymysql.MySQLError:
            time.sleep(2)
    if connection is None:
        raise SystemExit("Administrator connection did not become ready; check local configuration")
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database}`")
            cursor.execute("CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s", (user, values["SEEKDB_PASSWORD"]))
            cursor.execute(f"GRANT ALL PRIVILEGES ON `{database}`.* TO %s@'%%'", (user,))
        # Verify the supplied application password; do not reset any existing account's password.
        app = pymysql.connect(host=values.get("SEEKDB_HOST", "127.0.0.1"),
                              port=int(values.get("SEEKDB_PORT", "2881")), user=user,
                              password=values["SEEKDB_PASSWORD"], database=database, connect_timeout=5)
        app.close()
    finally:
        connection.close()
    print("Database and application access ready; no credentials displayed")


if __name__ == "__main__":
    main()
