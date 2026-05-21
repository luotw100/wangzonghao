from fastapi import APIRouter
from sqlalchemy.orm import joinedload

from chat.deps import CurrentAccountDep, DbDep
from chat.models import Conversation
from chat.schemas import ConversationRead
from chat.scoping import scoped


router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationRead])
def list_conversations(account: CurrentAccountDep, db: DbDep) -> list[Conversation]:
    """获取当前账号的所有一对一会话，按最后活跃时间降序排列（最新有消息的在前）。每条会话内嵌了联系人详情。"""
    return (
        scoped(db, account, Conversation)
        .options(joinedload(Conversation.contact))
        .order_by(Conversation.updated_at.desc())
        .all()
    )
