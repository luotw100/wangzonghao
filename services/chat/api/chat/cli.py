import argparse

from chat.auth_utils import hash_password
from chat.cli_render import danger, ok, render_table
from chat.db import ensure_database, get_db, utc_now
from chat.enums import AccountStatus
from chat.models import Account


def base_account_id(username: str) -> str:
    safe = "".join(ch for ch in username.lower() if ch.isalnum())[:12]
    return f"acct_{safe}" if safe else "acct_user"


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
            avatar_url=args.avatar_url,
            status=AccountStatus.ACTIVE,
            is_deleted=False,
            deleted_at=None,
            last_login_at=None,
            created_at=now,
            updated_at=now,
        )
        db.add(account)
        db.commit()
        print(ok(f"created chat account {account.username}"))
        print(render_table(
            ["id", "username", "display_name", "status"],
            [[account.id, account.username, account.display_name, account.status]],
        ))
    finally:
        db.close()


def list_accounts(_: argparse.Namespace) -> None:
    ensure_database()
    db = next(get_db())
    try:
        rows = []
        for account in db.query(Account).order_by(Account.created_at.asc()).all():
            status = danger(f"{account.status} deleted") if account.is_deleted else ok(account.status)
            rows.append([account.id, account.username, account.display_name, status])
        print(render_table(["id", "username", "display_name", "status"], rows))
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
        print(ok(f"updated password for {account.username}"))
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Laborster Chat debug accounts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create-account")
    create_parser.add_argument("--username", required=True)
    create_parser.add_argument("--password", required=True)
    create_parser.add_argument("--display-name", required=True)
    create_parser.add_argument("--avatar-url")
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
