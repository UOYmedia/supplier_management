from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.core.database import get_db
from app.models.scan_log import ScanLog
from app.models.user import User
from app.schemas.scan_log import ScanLogOut
from app.api.v1.auth import require_admin

router = APIRouter(prefix="/scan-logs", tags=["scan-logs"])


@router.get("", response_model=list[ScanLogOut])
async def list_scan_logs(
    status: str | None = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = select(ScanLog)
    if status:
        q = q.where(ScanLog.status == status)
    q = q.order_by(ScanLog.created_at.desc()).limit(min(limit, 1000))
    result = await db.execute(q)
    return result.scalars().all()


@router.delete("", status_code=204)
async def clear_scan_logs(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    await db.execute(delete(ScanLog))
    await db.commit()
