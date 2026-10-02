import os

from dotenv import load_dotenv

import random
import time

import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User

import bcrypt

load_dotenv()

router = APIRouter(prefix="/api", tags=["auth"])

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-fallback-secret")

#对称加密
ALGORITHM = "HS256"

TOKEN_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRE_SECONDS", "3600"))

# 验证码有效期（秒），300 = 5 分钟
CODE_EXPIRE_SECONDS = int(os.getenv("CODE_EXPIRE_SECONDS", "300"))

codes:dict = {}

def hash_password(password: str) -> str:
    """把明文密码转成 bcrypt 哈希。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """校验明文密码是否匹配 bcrypt 哈希。"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

class RegisterBody(BaseModel):
    username: str
    password: str

class LoginBody(BaseModel):
    username: str
    password: str

class SendCodeBody(BaseModel):
    username: str

class VerifyCodeBody(BaseModel):
    username: str
    code: str

class ResetPasswordBody(BaseModel):
    username: str
    new_password: str




@router.post("/register", status_code=201)
def register(body: RegisterBody, db: Session = Depends(get_db)):
    if not body.username or not body.password:
        raise HTTPException(status_code=400, detail="账号和密码不能为空")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")

    exists = db.query(User).filter(User.username == body.username).first()
    if exists:
        raise HTTPException(status_code=400, detail="账号已存在")

    user = User(username=body.username, password=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    return {"message": "注册成功", "id": user.id, "username": user.username}

@router.post("/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user:
        raise HTTPException(status_code=400,detail="账号不存在")

    # bcrypt 哈希以 $2 开头；旧数据是明文
    if user.password.startswith("$2"):
        if not verify_password(body.password, user.password):
            raise HTTPException(status_code=400, detail="密码错误")
    else:
        # 兼容旧明文数据：校验通过后自动升级成哈希
        if user.password != body.password:
            raise HTTPException(status_code=400, detail="密码错误")
        user.password = hash_password(body.password)
        db.commit()

    #组装JWT：把用户信息编码成一个加密字符串，前端保存后每次请求带上
    payload = {
        "id" : user.id,
        "username": user.username,
        # exp 是标准字段，PyJWT 会自动校验过期时间
        "exp":int(time.time()) + TOKEN_EXPIRE_SECONDS,
    }
    token = jwt.encode(payload,SECRET_KEY,algorithm=ALGORITHM)


    return {
        "message": "登录成功",
        "token": token,
        "username": user.username,
    }

@router.post("/send-code")
def send_code(body: SendCodeBody, db: Session = Depends(get_db)):
    username = db.query(User).filter(User.username == body.username).first()
    if not username:
        raise HTTPException(status_code=400,detail="用户不存在")

    code = f"{random.randint(100000,999999)}"

    codes[body.username] = {
        "code": code,
        "expires": int(time.time()) + CODE_EXPIRE_SECONDS,
    }

    return {"message": "验证码已发送", "code": code}

@router.post("/verify-code")
def verift_code(body: VerifyCodeBody,db: Session = Depends(get_db)):
    record = codes.get(body.username)

    if not record:
        raise HTTPException(status_code=400,detail="请先获取验证码")

    if time.time() > record["expires"]:
        codes.pop(body.username, None)
        raise HTTPException(status_code=400,detail="验证码已过期")

    if record["code"] != body.code:
        raise  HTTPException(status_code=400,detail="验证码错误")

    codes.pop(body.username, None)

    try:
        user = db.query(User).filter(User.username == body.username).first()
        if not user:
            raise HTTPException(status_code=400,detail="不存在该用户")
        return {"message": "验证通过"}
    finally:
        db.close()

@router.post("/reset-password")
def reset_password(body: ResetPasswordBody, db: Session = Depends(get_db)):
    if not body.new_password or len(body.new_password) < 6:
        raise HTTPException(status_code=400,detail="密码至少六位")

    user = db.query(User).filter(User.username == body.username).first()
    if not user:
        raise HTTPException(status_code=400, detail="用户不存在")

    user.password = hash_password(body.new_password)
    db.commit()

    return {"message": "密码修改成功"}



