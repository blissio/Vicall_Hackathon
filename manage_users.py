"""Create/update a team account with a salted password hash."""
import argparse
import getpass
import json
from pathlib import Path
from serve import hash_password

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("--role", choices=("viewer", "researcher", "admin"), default="researcher")
    parser.add_argument("--users", type=Path, default=Path("users.json"))
    args = parser.parse_args()
    password = getpass.getpass("New password (at least 12 characters): ")
    if len(password) < 12 or password != getpass.getpass("Confirm password: "):
        parser.error("Passwords must match and contain at least 12 characters")
    users = json.loads(args.users.read_text(encoding="utf-8")) if args.users.exists() else {}
    users[args.username] = {"role": args.role, **hash_password(password)}
    temporary = args.users.with_suffix(".tmp")
    temporary.write_text(json.dumps(users, indent=2), encoding="utf-8")
    temporary.replace(args.users)
    print("Account hash saved. Protect this file and restart the team server to apply account changes.")
