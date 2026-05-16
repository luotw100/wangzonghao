import argparse

from prettytable import PrettyTable, SINGLE_BORDER

from studio.auth_utils import hash_password
from studio.db import get_db, utc_now
from studio.deps import new_id
from studio.enums import AccountRole, AccountStatus
from studio.migrate import run_migrations
from studio.models import Account


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
        account_id = new_id("acc")
        now = utc_now()
        account = Account(
            id=account_id,
            username=args.username,
            password_hash=hash_password(args.password),
            display_name=args.display_name,
            role=args.role,
            status=AccountStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            last_login_at=None,
        )
        db.add(account)
        db.commit()
        print(f"created studio account {account.username}")
        print(_table(
            ["id", "username", "display_name", "role", "status"],
            [[account.id, account.username, account.display_name, account.role, account.status]],
        ))
    finally:
        db.close()


def list_accounts(_: argparse.Namespace) -> None:
    run_migrations()
    db = next(get_db())
    try:
        rows = []
        for account in db.query(Account).order_by(Account.created_at.asc()).all():
            rows.append([account.id, account.username, account.display_name or "", account.role, account.status])
        print(_table(["id", "username", "display_name", "role", "status"], rows))
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


def set_role(args: argparse.Namespace) -> None:
    run_migrations()
    db = next(get_db())
    try:
        account = db.query(Account).filter(Account.username == args.username).first()
        if not account:
            raise SystemExit(f"account not found: {args.username}")
        account.role = args.role
        account.updated_at = utc_now()
        db.commit()
        print(f"updated role for {account.username} -> {account.role}")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Laborster Studio accounts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create-account")
    create_parser.add_argument("--username", required=True)
    create_parser.add_argument("--password", required=True)
    create_parser.add_argument("--display-name", required=True)
    create_parser.add_argument("--role", choices=[r.value for r in AccountRole], required=True)
    create_parser.set_defaults(func=create_account)

    list_parser = subparsers.add_parser("list-accounts")
    list_parser.set_defaults(func=list_accounts)

    reset_parser = subparsers.add_parser("reset-password")
    reset_parser.add_argument("--username", required=True)
    reset_parser.add_argument("--password", required=True)
    reset_parser.set_defaults(func=reset_password)

    role_parser = subparsers.add_parser("set-role")
    role_parser.add_argument("--username", required=True)
    role_parser.add_argument("--role", choices=[r.value for r in AccountRole], required=True)
    role_parser.set_defaults(func=set_role)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
