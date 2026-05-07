import argparse

from robot.auth_utils import hash_password
from robot.db import ensure_database, get_db, utc_now
from robot.models import Account


def base_account_id(username: str) -> str:
    safe = "".join(ch for ch in username.lower() if ch.isalnum())[:12]
    return f"acc_{safe}" if safe else "acc_user"


def create_account(args: argparse.Namespace) -> None:
    ensure_database()
    db = next(get_db())
    try:
        existing = db.query(Account).filter(Account.username == args.username).first()
        if existing:
            raise SystemExit(f"account already exists: {args.username}")
        account_id = base_account_id(args.username)
        suffix = 1
        while db.query(Account).filter(Account.id == account_id).first():
            suffix += 1
            account_id = f"{base_account_id(args.username)}_{suffix}"
        now = utc_now()
        account = Account(
            id=account_id,
            username=args.username,
            password_hash=hash_password(args.password),
            display_name=args.display_name,
            status="active",
            created_at=now,
            updated_at=now,
            last_login_at=None,
        )
        db.add(account)
        db.commit()
        print(
            f"created {account.id} username={account.username} display_name={account.display_name}"
        )
    finally:
        db.close()


def list_accounts(_: argparse.Namespace) -> None:
    ensure_database()
    db = next(get_db())
    try:
        for account in db.query(Account).order_by(Account.created_at.asc()).all():
            print(
                f"{account.id}\t{account.username}\t{account.display_name or ''}\t{account.status}"
            )
    finally:
        db.close()


def reset_password(args: argparse.Namespace) -> None:
    ensure_database()
    db = next(get_db())
    try:
        account = db.query(Account).filter(Account.username == args.username).first()
        if not account:
            raise SystemExit(f"account not found: {args.username}")
        account.password_hash = hash_password(args.password)
        account.updated_at = utc_now()
        db.commit()
        print(f"updated password for {account.username}")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Laborster Robot accounts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create-account")
    create_parser.add_argument("--username", required=True)
    create_parser.add_argument("--password", required=True)
    create_parser.add_argument("--display-name", required=True)
    create_parser.set_defaults(func=create_account)

    list_parser = subparsers.add_parser("list-accounts")
    list_parser.set_defaults(func=list_accounts)

    reset_parser = subparsers.add_parser("reset-password")
    reset_parser.add_argument("--username", required=True)
    reset_parser.add_argument("--password", required=True)
    reset_parser.set_defaults(func=reset_password)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
