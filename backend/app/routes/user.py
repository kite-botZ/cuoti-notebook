"""用户中心：查看个人信息、修改密码。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.routes.auth import hash_password, verify_password
from app.routes.banks import current_user_id

router = APIRouter(prefix="/api/user", tags=["user"])


class ChangePasswordBody(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=6, max_length=128)


@router.get("/me")
def get_me(
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """返回当前登录用户的基本信息。"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {
        "id": user.id,
        "username": user.username,
        "created_at": user.created_at,
    }


@router.post("/change-password")
def change_password(
    body: ChangePasswordBody,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """修改当前登录用户的密码。"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 校验旧密码（兼容旧明文和 bcrypt 哈希）
    if user.password.startswith("$2"):
        if not verify_password(body.old_password, user.password):
            raise HTTPException(status_code=400, detail="原密码错误")
    else:
        if user.password != body.old_password:
            raise HTTPException(status_code=400, detail="原密码错误")

    if body.old_password == body.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")

    user.password = hash_password(body.new_password)
    db.commit()
    return {"message": "密码修改成功"}