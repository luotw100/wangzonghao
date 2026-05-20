import argparse

from prettytable import PrettyTable, SINGLE_BORDER

from studio.auth_utils import hash_password
from studio.clients import ALLOWED_BASE_URLS
from studio.db import get_db, utc_now
from studio.deps import new_id
from studio.enums import AccountStatus
from studio.migrate import run_migrations
from studio.models import Account, ProviderConfig


def _table(headers: list[str], rows: list[list]) -> str:
    t = PrettyTable(field_names=headers)
    t.set_style(SINGLE_BORDER)
    t.align = "l"
    for row in rows:
        t.add_row(["" if cell is None else str(cell) for cell in row])
    return t.get_string()


def _mask_api_key(api_key: str | None) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


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
            status=AccountStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        db.add(account)
        db.commit()
        print(f"created studio account {account.username}")
        print(_table(
            ["id", "username", "display_name", "status"],
            [[account.id, account.username, account.display_name, account.status]],
        ))
    finally:
        db.close()


def list_accounts(_: argparse.Namespace) -> None:
    run_migrations()
    db = next(get_db())
    try:
        rows = []
        for account in db.query(Account).order_by(Account.created_at.asc()).all():
            rows.append([account.id, account.username, account.display_name or "", account.status])
        print(_table(["id", "username", "display_name", "status"], rows))
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


def _validate_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized not in ALLOWED_BASE_URLS:
        raise SystemExit(f"base_url not in whitelist: {base_url!r}")
    return normalized


def create_provider(args: argparse.Namespace) -> None:
    """Create a Provider. The most-recently-updated one is treated as the
    system default by reply/distill until per-contact provider routing is
    wired through the UI.
    """
    run_migrations()
    db = next(get_db())
    try:
        now = utc_now()
        p = ProviderConfig(
            id=new_id("p"),
            name=args.name,
            base_url=_validate_base_url(args.base_url),
            api_key=args.api_key,
            model=args.model,
            created_at=now,
            updated_at=now,
        )
        db.add(p)
        db.commit()
        print(f"created studio provider {p.name}")
        print(_table(
            ["id", "name", "base_url", "model", "api_key"],
            [[p.id, p.name, p.base_url, p.model, _mask_api_key(p.api_key)]],
        ))
    finally:
        db.close()


def list_providers(_: argparse.Namespace) -> None:
    run_migrations()
    db = next(get_db())
    try:
        rows = []
        for p in db.query(ProviderConfig).order_by(ProviderConfig.updated_at.desc()).all():
            rows.append([p.id, p.name, p.base_url, p.model, _mask_api_key(p.api_key)])
        print(_table(
            ["id", "name", "base_url", "model", "api_key"],
            rows,
        ))
    finally:
        db.close()


def delete_provider(args: argparse.Namespace) -> None:
    run_migrations()
    db = next(get_db())
    try:
        p = db.query(ProviderConfig).filter(ProviderConfig.id == args.id).first()
        if not p:
            raise SystemExit(f"provider not found: {args.id}")
        db.delete(p)
        db.commit()
        print(f"deleted studio provider {args.id}")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Laborster Studio accounts and providers")
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

    pcreate_parser = subparsers.add_parser("create-provider")
    pcreate_parser.add_argument("--name", required=True)
    pcreate_parser.add_argument("--base-url", required=True)
    pcreate_parser.add_argument("--api-key", default=None)
    pcreate_parser.add_argument("--model", required=True)
    pcreate_parser.set_defaults(func=create_provider)

    plist_parser = subparsers.add_parser("list-providers")
    plist_parser.set_defaults(func=list_providers)

    pdelete_parser = subparsers.add_parser("delete-provider")
    pdelete_parser.add_argument("--id", required=True)
    pdelete_parser.set_defaults(func=delete_provider)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
