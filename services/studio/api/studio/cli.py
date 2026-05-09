import argparse
from uuid import uuid4

from studio.auth_utils import hash_password
from studio.cli_render import danger, ok, render_table, warn
from studio.db import ensure_database, get_db, utc_now
from studio.enums import AccountRole, AccountStatus
from studio.models import Account


def create_account(args: argparse.Namespace) -> None:
    ensure_database()
    db = next(get_db())
    try:
        existing = db.query(Account).filter(Account.username == args.username).first()
        if existing:
            raise SystemExit(f"account already exists: {args.username}")
        account_id = f"acc_{uuid4().hex[:8]}"
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
        print(ok(f"created studio account {account.username}"))
        print(render_table(
            ["id", "username", "display_name", "role", "status"],
            [[account.id, account.username, account.display_name, account.role, account.status]],
        ))
    finally:
        db.close()


def list_accounts(_: argparse.Namespace) -> None:
    ensure_database()
    db = next(get_db())
    try:
        rows = []
        for account in db.query(Account).order_by(Account.created_at.asc()).all():
            role = warn(account.role) if account.role == AccountRole.ADMIN else account.role
            status = ok(account.status) if account.status == AccountStatus.ACTIVE else danger(account.status)
            rows.append([account.id, account.username, account.display_name or "", role, status])
        print(render_table(["id", "username", "display_name", "role", "status"], rows))
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


def set_role(args: argparse.Namespace) -> None:
    ensure_database()
    db = next(get_db())
    try:
        account = db.query(Account).filter(Account.username == args.username).first()
        if not account:
            raise SystemExit(f"account not found: {args.username}")
        account.role = args.role
        account.updated_at = utc_now()
        db.commit()
        print(ok(f"updated role for {account.username} -> {account.role}"))
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
