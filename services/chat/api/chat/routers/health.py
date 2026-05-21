from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """健康检查。返回 `{"status": "ok"}`，可用于负载均衡探活。"""
    return {"status": "ok"}
