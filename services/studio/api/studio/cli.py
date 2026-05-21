import argparse

from prettytable import PrettyTable, SINGLE_BORDER

from studio.auth_utils import hash_password
from studio.clients import ALLOWED_BASE_URLS
from studio.db import get_db, utc_now
from studio.deps import new_id, pick_first_provider
from studio.enums import AccountStatus
from studio.models import Account, Contact, Inbox, Persona, ProviderConfig


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
    db = next(get_db())
    try:
        existing = db.query(Account).filter(Account.username == args.username).first()
        if existing:
            raise SystemExit(f"account already exists: {args.username}")
        provider = pick_first_provider(db)
        if not provider:
            raise SystemExit("no provider configured; run create-provider first")
        account_id = new_id("acc")
        now = utc_now()
        account = Account(
            id=account_id,
            username=args.username,
            password_hash=hash_password(args.password),
            display_name=args.display_name,
            status=AccountStatus.ACTIVE,
            distill_provider_id=provider.id,
            created_at=now,
            updated_at=now,
        )
        db.add(account)
        db.commit()
        print(f"created studio account {account.username} (distill provider: {provider.name})")
        print(_table(
            ["id", "username", "display_name", "status", "distill_provider"],
            [[account.id, account.username, account.display_name, account.status, provider.name]],
        ))
    finally:
        db.close()


def list_accounts(_: argparse.Namespace) -> None:
    db = next(get_db())
    try:
        rows = []
        for account, provider_name in (
            db.query(Account, ProviderConfig.name)
            .join(ProviderConfig, ProviderConfig.id == Account.distill_provider_id)
            .order_by(Account.created_at.asc())
            .all()
        ):
            rows.append([account.id, account.username, account.display_name or "", account.status, provider_name])
        print(_table(["id", "username", "display_name", "status", "distill_provider"], rows))
    finally:
        db.close()


def reset_password(args: argparse.Namespace) -> None:
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
    db = next(get_db())
    try:
        existing = db.query(ProviderConfig).filter(ProviderConfig.name == args.name).first()
        if existing:
            raise SystemExit(f"provider already exists: {args.name} ({existing.id})")
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
    db = next(get_db())
    try:
        rows = []
        for p in db.query(ProviderConfig).order_by(ProviderConfig.created_at.asc()).all():
            rows.append([p.id, p.name, p.base_url, p.model, _mask_api_key(p.api_key)])
        print(_table(
            ["id", "name", "base_url", "model", "api_key"],
            rows,
        ))
    finally:
        db.close()


def update_provider(args: argparse.Namespace) -> None:
    db = next(get_db())
    try:
        p = db.query(ProviderConfig).filter(ProviderConfig.id == args.id).first()
        if not p:
            raise SystemExit(f"provider not found: {args.id}")
        if args.name is not None:
            clash = db.query(ProviderConfig).filter(
                ProviderConfig.name == args.name, ProviderConfig.id != p.id,
            ).first()
            if clash:
                raise SystemExit(f"provider name already in use: {args.name} ({clash.id})")
            p.name = args.name
        if args.base_url is not None:
            p.base_url = _validate_base_url(args.base_url)
        if args.api_key is not None:
            p.api_key = args.api_key
        if args.model is not None:
            p.model = args.model
        p.updated_at = utc_now()
        db.commit()
        print(f"updated studio provider {p.name}")
        print(_table(
            ["id", "name", "base_url", "model", "api_key"],
            [[p.id, p.name, p.base_url, p.model, _mask_api_key(p.api_key)]],
        ))
    finally:
        db.close()


def delete_provider(args: argparse.Namespace) -> None:
    db = next(get_db())
    try:
        p = db.query(ProviderConfig).filter(ProviderConfig.id == args.id).first()
        if not p:
            raise SystemExit(f"provider not found: {args.id}")
        contact_refs = db.query(Contact).filter(Contact.provider_id == p.id).count()
        account_refs = db.query(Account).filter(Account.distill_provider_id == p.id).count()
        if contact_refs or account_refs:
            raise SystemExit(
                f"provider {p.id} is referenced by {contact_refs} contact(s) and "
                f"{account_refs} account(s); reassign via set-contact-provider / "
                "set-distill-provider before deleting"
            )
        db.delete(p)
        db.commit()
        print(f"deleted studio provider {args.id}")
    finally:
        db.close()


def list_contacts(args: argparse.Namespace) -> None:
    db = next(get_db())
    try:
        q = (
            db.query(
                Contact, Account.username, Inbox.platform, Inbox.display_name,
                Persona.name, ProviderConfig.name,
            )
            .join(Inbox, Inbox.id == Contact.inbox_id)
            .join(Account, Account.id == Inbox.account_id)
            .join(ProviderConfig, ProviderConfig.id == Contact.provider_id)
            .outerjoin(Persona, Persona.id == Contact.persona_id)
        )
        if args.account:
            account = db.query(Account).filter(Account.username == args.account).first()
            if not account:
                raise SystemExit(f"account not found: {args.account}")
            q = q.filter(Inbox.account_id == account.id)
        q = q.order_by(Account.username.asc(), Inbox.display_name.asc(), Contact.created_at.asc(), Contact.id.asc())

        rows = []
        for c, username, platform, inbox_name, persona_name, provider_name in q.all():
            rows.append([
                c.id, username, f"{platform}:{inbox_name}", c.display_name,
                persona_name or "", provider_name,
                c.reply_policy, "Y" if c.takeover else "", c.status,
            ])
        print(_table(
            ["id", "account", "inbox", "peer", "persona", "provider", "reply_policy", "takeover", "status"],
            rows,
        ))
    finally:
        db.close()


def set_contact_provider(args: argparse.Namespace) -> None:
    db = next(get_db())
    try:
        c = db.query(Contact).filter(Contact.id == args.contact).first()
        if not c:
            raise SystemExit(f"contact not found: {args.contact}")
        p = db.query(ProviderConfig).filter(ProviderConfig.id == args.provider).first()
        if not p:
            raise SystemExit(f"provider not found: {args.provider}")
        c.provider_id = p.id
        c.updated_at = utc_now()
        db.commit()
        print(f"contact {c.id} now uses provider {p.name}")
    finally:
        db.close()


def set_distill_provider(args: argparse.Namespace) -> None:
    db = next(get_db())
    try:
        a = db.query(Account).filter(Account.username == args.account).first()
        if not a:
            raise SystemExit(f"account not found: {args.account}")
        p = db.query(ProviderConfig).filter(ProviderConfig.id == args.provider).first()
        if not p:
            raise SystemExit(f"provider not found: {args.provider}")
        a.distill_provider_id = p.id
        a.updated_at = utc_now()
        db.commit()
        print(f"account {a.username} distill provider set to {p.name}")
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

    pupdate_parser = subparsers.add_parser("update-provider")
    pupdate_parser.add_argument("--id", required=True)
    pupdate_parser.add_argument("--name", default=None)
    pupdate_parser.add_argument("--base-url", default=None)
    pupdate_parser.add_argument("--api-key", default=None)
    pupdate_parser.add_argument("--model", default=None)
    pupdate_parser.set_defaults(func=update_provider)

    pdelete_parser = subparsers.add_parser("delete-provider")
    pdelete_parser.add_argument("--id", required=True)
    pdelete_parser.set_defaults(func=delete_provider)

    lcontacts_parser = subparsers.add_parser("list-contacts")
    lcontacts_parser.add_argument("--account", default=None, help="只列出该账号名下的 contact（按 username）；省略则列全部")
    lcontacts_parser.set_defaults(func=list_contacts)

    setcp_parser = subparsers.add_parser("set-contact-provider")
    setcp_parser.add_argument("--contact", required=True, help="Contact ID")
    setcp_parser.add_argument("--provider", required=True, help="Provider ID")
    setcp_parser.set_defaults(func=set_contact_provider)

    setdp_parser = subparsers.add_parser("set-distill-provider")
    setdp_parser.add_argument("--account", required=True, help="Account username")
    setdp_parser.add_argument("--provider", required=True, help="Provider ID")
    setdp_parser.set_defaults(func=set_distill_provider)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
