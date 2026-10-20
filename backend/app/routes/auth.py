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
from app.security import ALGORITHM, SECRET_KEY

import bcrypt

load_dotenv()

router = APIRouter(prefix="/api", tags=["auth"])

APP_ENV = os.getenv("APP_ENV", "development")

TOKEN_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRE_SECONDS", "3600"))

# 验证码有效期（秒），300 = 5 分钟
CODE_EXPIRE_SECONDS = int(os.getenv("CODE_EXPIRE_SECONDS", "300"))

# 「验证通过」之后发给前端的重置凭证有效期（秒）
RESET_TICKET_SECONDS = int(os.getenv("RESET_TICKET_SECONDS", "600"))

# 是否把验证码直接放在接口响应里返回。
# 开发环境开着方便调试；**生产环境默认关闭**，否则等于任何人输入一个用户名
# 就能拿到验证码，进而重置别人的密码。
# 真实上线应该把验证码通过短信 / 邮件发出去，而不是从接口读回来。
AUTH_ECHO_CODE = os.getenv(
    "AUTH_ECHO_CODE", "1" if APP_ENV != "production" else "0"
) == "1"

codes: dict = {}
# 完成验证码校验的用户 -> 凭证到期时间戳
reset_tickets: dict = {}

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

    payload = {"message": "验证码已发送"}
    if AUTH_ECHO_CODE:
        # 只有开发环境才把验证码回显，方便本地调试。
        # 生产环境（AUTH_ECHO_CODE=0）应该把验证码通过短信 / 邮件发出去。
        payload["code"] = code
    return payload

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

    user = db.query(User).filter(User.username == body.username).first()
    if not user:
        raise HTTPException(status_code=400,detail="不存在该用户")

    # 校验通过后发一张短时「重置凭证」。
    # reset-password 必须凭这张凭证才能改密码，否则就是下面那个漏洞：
    # 任何人只要知道用户名就能直接调 /reset-password 把别人密码改掉。
    reset_tickets[body.username] = int(time.time()) + RESET_TICKET_SECONDS

    return {"message": "验证通过"}

@router.post("/reset-password")
def reset_password(body: ResetPasswordBody, db: Session = Depends(get_db)):
    if not body.new_password or len(body.new_password) < 6:
        raise HTTPException(status_code=400,detail="密码至少六位")

    # 修复：原来这里只校验了「用户存在 + 新密码长度」，**完全不验证验证码**，
    # 于是任何人 POST 一个用户名就能改掉别人的密码 —— 公开部署等于把账号送人。
    # 现在必须先在 /verify-code 拿到重置凭证，并且凭证未过期。
    deadline = reset_tickets.get(body.username)
    if not deadline or time.time() > deadline:
        reset_tickets.pop(body.username, None)
        raise HTTPException(status_code=400, detail="请先完成验证码校验")

    user = db.query(User).filter(User.username == body.username).first()
    if not user:
        raise HTTPException(status_code=400, detail="用户不存在")

    user.password = hash_password(body.new_password)
    db.commit()

    # 凭证一次性使用，改完密码立即失效
    reset_tickets.pop(body.username, None)

    return {"message": "密码修改成功"}



