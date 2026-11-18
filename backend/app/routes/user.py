"""用户中心：查看个人信息、修改密码。"""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.routes.auth import hash_password, verify_password
from app.routes.banks import current_user_id
from app.security import MEDIA_COOKIE

router = APIRouter(prefix="/api/user", tags=["user"])


class ChangePasswordBody(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
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
    response: Response,
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
    # 吊销所有已签发的 token（含当前这一个）。
    # 改密码的语义就是"其它地方的登录不再有效"——包括可能已经泄露的那份，
    # 否则改完密码后攻击者还能用旧 token 继续操作最多一小时。
    # 前端拿到 200 就直接登出了（Home.vue 的 changePassword），
    # 所以这里不需要回传新 token。
    user.token_version = (user.token_version or 1) + 1
    db.commit()

    # 图片用的 cookie 也跟着作废，避免"已登出但还能看图"
    response.delete_cookie(key=MEDIA_COOKIE, path="/")
    return {"message": "密码修改成功，请重新登录"}