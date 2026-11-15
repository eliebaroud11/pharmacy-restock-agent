"""Create a pharmacist account from the command line (the password is typed hidden).

  python scripts/add_user.py            -> asks for name, username, password
  python scripts/add_user.py --admin    -> the account can manage other accounts
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pharmacy import auth, db  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--admin", action="store_true")
    args = ap.parse_args()
    conn = db.connect()
    full = input("Full name: ")
    username = input("Username: ")
    pw = getpass.getpass("Password (hidden): ")
    if pw != getpass.getpass("Confirm password: "):
        sys.exit("Passwords don't match.")
    try:
        # Whoever can run commands on this computer can already open the database, so they count as admin here.
        auth.create_user(conn, username, full, pw, is_admin=args.admin, actor="command line", by_admin=True)
    except auth.AuthError as e:
        sys.exit(str(e))
    print(f"Created account '{username}'{' (administrator)' if args.admin else ''}.")


if __name__ == "__main__":
    main()
