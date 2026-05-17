import argparse

from prettytable import PrettyTable, SINGLE_BORDER

from chat.auth_utils import hash_password
from chat.db import get_db, utc_now
from chat.enums import AccountStatus
from chat.ids import new_id
from chat.migrate import run_migrations
from chat.models import Account


def _table(headers: list[str], rows: list[list]) -> str:
    t = PrettyTable(field_names=headers)
    t.set_style(SINGLE_BORDER)
    t.align = "l"
    for row in rows:
        t.add_row(["" if cell is None else str(cell) for cell in row])
    return t.get_string()


def create_account(args: argparse.Namespace) -> None:
    run_migrations()
    db = next(get_db())
    try:
        existing = db.query(Account).filter(Account.username == args.username).first()
        if existing:
            raise SystemExit(f"account already exists: {args.username}")
        now = utc_now()
        account = Account(
            id=new_id("acct"),
            username=args.username,
            password_hash=hash_password(args.password),
            nickname=args.nickname,
            status=AccountStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        db.add(account)
        db.commit()
        print(f"created chat account {account.username}")
        print(_table(
            ["id", "username", "nickname", "status"],
            [[account.id, account.username, account.nickname, account.status]],
        ))
    finally:
        db.close()


def list_accounts(_: argparse.Namespace) -> None:
    run_migrations()
    db = next(get_db())
    try:
        rows = [
            [account.id, account.username, account.nickname, account.status]
            for account in db.query(Account).order_by(Account.created_at.asc()).all()
        ]
        print(_table(["id", "username", "nickname", "status"], rows))
    finally:
        db.close()


def reset_password(args: argparse.Namespace) -> None:
    run_migrations()
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
    parser = argparse.ArgumentParser(description="Manage Laborster Chat debug accounts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create-account")
    create_parser.add_argument("--username", required=True)
    create_parser.add_argument("--password", required=True)
    create_parser.add_argument("--nickname", required=True)
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
