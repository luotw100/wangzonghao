from fastapi import APIRouter, HTTPException

from chat.config import DISALLOWED_UPLOAD_MIME_TYPES, UPLOAD_MAX_SIZE_BYTES
from chat.deps import CurrentAccountDep
from chat.s3 import s3_generate_storage_key, s3_presigned_post
from chat.schemas import UploadPresignRequest, UploadPresignResponse


router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@router.post("/presign", response_model=UploadPresignResponse)
def presign_upload(
    payload: UploadPresignRequest,
    account: CurrentAccountDep,
) -> UploadPresignResponse:
    """申请媒体文件上传的预签名信息。

    返回 `upload_url`（S3 地址）和 `fields`（签名表单字段）。
    客户端用 multipart/form-data 把 fields 里的所有键值对加上文件二进制（key='file'）一起 POST 到 upload_url，
    S3 返回 204 表示上传成功。
    上传完成后，将返回的 `storage_key` 填入消息的 content 字段发送即可。

    注意：text/html、application/xhtml+xml、image/svg+xml 等 MIME 类型会被拒绝（防止存储型 XSS）。
    """
    if payload.mime_type.split(";")[0].strip().lower() in DISALLOWED_UPLOAD_MIME_TYPES:
        raise HTTPException(status_code=400, detail="不支持的文件类型")
    storage_key = s3_generate_storage_key(account.id)
    post = s3_presigned_post(storage_key, payload.mime_type, UPLOAD_MAX_SIZE_BYTES)
    return UploadPresignResponse(
        storage_key=storage_key,
        upload_url=post["url"],
        fields=post["fields"],
    )
