"""Desktop-app download handout.

Gated on a normal account login: there is no public signup, so "has an
account" == "is invited". The portal at laborster.com logs in via
``POST /api/auth/login`` then calls this endpoint with the bearer token;
we mint a short-lived S3 presigned URL for the current installer and
record the handout in ``download_events``.

Returns JSON ``{url: ...}`` rather than a 302 on purpose: the portal does
a cross-origin ``fetch`` with the Authorization header, and a redirect to
S3 would drag that header along / trip CORS. The browser navigates to
``url`` itself.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request

from studio.db import utc_now
from studio.deps import CurrentAccountDep, DbDep
from studio.models import DownloadEvent, Release
from studio.s3 import s3_presigned_get_url
from studio.schemas import DownloadInfo

router = APIRouter()

ALLOWED_PLATFORMS = ("win", "mac")


def _client_ip(request: Request, x_forwarded_for: Optional[str]) -> Optional[str]:
    # Edge (Caddy → frp) prepends the real client to X-Forwarded-For; take the
    # first hop. Fall back to the socket peer for direct/dev access.
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


@router.get("/api/download/latest", response_model=DownloadInfo)
def download_latest(
    account: CurrentAccountDep,
    db: DbDep,
    request: Request,
    platform: Annotated[str, Query(description="win / mac")],
    user_agent: Annotated[Optional[str], Header()] = None,
    x_forwarded_for: Annotated[Optional[str], Header()] = None,
):
    """拉取当前最新桌面安装包的预签名下载直链（需登录）。

    按 platform 取 is_latest 的发布版本，签发短时有效的 S3 直链，并记一条
    download_events 审计。无对应平台的已发布版本时返回 404。
    """
    if platform not in ALLOWED_PLATFORMS:
        raise HTTPException(status_code=400, detail="platform 必须是 win / mac")

    rel = (
        db.query(Release)
        .filter(Release.platform == platform, Release.is_latest.is_(True))
        .first()
    )
    if not rel:
        raise HTTPException(status_code=404, detail="该平台暂无可下载版本")

    url = s3_presigned_get_url(rel.s3_key, filename=rel.filename)

    db.add(DownloadEvent(
        account_id=account.id,
        version=rel.version,
        platform=rel.platform,
        ip=_client_ip(request, x_forwarded_for),
        user_agent=(user_agent or None),
        created_at=utc_now(),
    ))
    db.commit()

    return {
        "version": rel.version,
        "platform": rel.platform,
        "url": url,
        "filename": rel.filename,
        "sha256": rel.sha256,
        "size_bytes": rel.size_bytes,
    }
