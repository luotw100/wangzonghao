from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from chat.deps import DbDep, MediaAccountDep
from chat.enums import MessageType
from chat.models import Message
from chat.s3 import s3_presigned_get_url
from chat.scoping import scoped


router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("/{storage_key:path}")
def serve_media(
    storage_key: str,
    account: MediaAccountDep,
    db: DbDep,
) -> RedirectResponse:
    """获取媒体文件访问链接（302 重定向到 S3 预签名 URL）。

    只允许访问属于当前账号的文件（storage key 必须以 `media/{account_id}/` 开头），否则返回 403。
    鉴权支持两种方式：Header `Authorization: Bearer <token>` 或 Query 参数 `?token=<token>`，
    后者方便在 `<img>`/`<video>` 等标签的 src 属性中直接使用。

    根据消息类型自动决定 Content-Disposition：
    - image/audio/video 类型设为 inline（浏览器直接预览）；
    - file 类型或尚未关联到任何消息的文件设为 attachment（强制下载）。
    """
    expected_prefix = f"media/{account.id}/"
    if not storage_key.startswith(expected_prefix):
        raise HTTPException(status_code=403, detail="无权访问该文件")

    msg_type = (
        scoped(db, account, Message)
        .filter(Message.content == storage_key)
        .with_entities(Message.msg_type)
        .limit(1)
        .scalar()
    )
    inline_types = {MessageType.IMAGE, MessageType.AUDIO, MessageType.VIDEO}
    force_attachment = msg_type not in inline_types
    url = s3_presigned_get_url(storage_key, force_attachment=force_attachment)
    return RedirectResponse(url=url)
