from sqlalchemy.orm import Session

from studio.models import Account


def scoped(db: Session, account: Account, model):
    """按账号隔离的查询入口。所有 per-account 表查询都应走这里，避免漏写 account_id 过滤导致越权。"""
    if not hasattr(model, "account_id"):
        raise TypeError(f"{model.__name__} 不是 account-scoped 模型")
    return db.query(model).filter(model.account_id == account.id)
