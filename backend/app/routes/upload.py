import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.routes.banks import current_user_id

router = APIRouter(prefix="/api", tags=["uploads"])

# 图片保存目录
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
MAX_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    user_id: int = Depends(current_user_id),
):
    """
    上传图片，返回可访问的 URL。
    返回格式：{ "url": "/uploads/202609/abc.jpg" }
    """
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=422, detail=f"不支持的图片格式：{ext}")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="文件是空的")
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="图片超过 5MB")

    # 按年月分目录，避免一个目录堆几万个文件
    sub_dir = datetime.now().strftime("%Y%m")
    target_dir = UPLOAD_DIR / sub_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}{ext}"
    target_path = target_dir / filename

    with open(target_path, "wb") as f:
        f.write(content)

    return {
        "url": f"/uploads/{sub_dir}/{filename}",
        "size": len(content),
    }