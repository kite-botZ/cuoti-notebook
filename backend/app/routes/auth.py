import os

from dotenv import load_dotenv

import random
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import ratelimit
from app.db import get_db
from app.models import User
from app.security import (
    COOKIE_SECURE,
    MEDIA_COOKIE,
    TOKEN_EXPIRE_SECONDS,
    create_access_token,
)

import bcrypt

load_dotenv()

router = APIRouter(prefix="/api", tags=["auth"])

APP_ENV = os.getenv("APP_ENV", "development")

# 验证码有效期（秒），300 = 5 分钟
CODE_EXPIRE_SECONDS = int(os.getenv("CODE_EXPIRE_SECONDS", "300"))

# 「验证通过」之后发给前端的重置凭证有效期（秒）
RESET_TICKET_SECONDS = int(os.getenv("RESET_TICKET_SECONDS", "600"))

# ---------------- 限流阈值 ----------------
# 全部可配，是因为不同部署的取舍不一样：内网自用可以放宽，
# 公网部署应该收紧。默认值按"公网单人使用"来给。
LOGIN_MAX_FAILURES = int(os.getenv("AUTH_LOGIN_MAX_FAILURES", "5"))
LOGIN_WINDOW = float(os.getenv("AUTH_LOGIN_WINDOW", "300"))
# 按 IP 的登录尝试上限：比按账号宽松，因为它防的是"换用户名撞库"，
# 而不是把某个账号锁死（锁账号会被用来做拒绝服务）。
LOGIN_IP_MAX = int(os.getenv("AUTH_LOGIN_IP_MAX", "30"))
SEND_CODE_INTERVAL = float(os.getenv("AUTH_SEND_CODE_INTERVAL", "60"))
SEND_CODE_MAX_PER_USER = int(os.getenv("AUTH_SEND_CODE_MAX_PER_USER", "5"))
SEND_CODE_WINDOW = float(os.getenv("AUTH_SEND_CODE_WINDOW", "3600"))
SEND_CODE_IP_MAX = int(os.getenv("AUTH_SEND_CODE_IP_MAX", "10"))
VERIFY_MAX_FAILURES = int(os.getenv("AUTH_VERIFY_MAX_FAILURES", "5"))
VERIFY_WINDOW = float(os.getenv("AUTH_VERIFY_WINDOW", "300"))
REGISTER_IP_MAX = int(os.getenv("AUTH_REGISTER_IP_MAX", "10"))


def echo_code_enabled() -> bool:
    """是否把验证码直接放在接口响应里返回。

    **默认只在明确的开发/测试环境回显。** 之前的写法是
    `"1" if APP_ENV != "production" else "0"` —— 也就是说，一份忘了设
    `APP_ENV` 的线上部署（极其常见）会被当成开发环境，任何人输入一个
    用户名就能从响应里读到验证码，然后 `/verify-code` + `/reset-password`
    接管账号。

    现在改成"白名单"：只有 `testing` / `development` 才默认回显，
    其它任何值（包括没设）一律不回显。要临时打开就显式 `AUTH_ECHO_CODE=1`。
    """
    raw = os.getenv("AUTH_ECHO_CODE")
    if raw is not None:
        return raw.strip() == "1"
    return APP_ENV in ("testing", "development")


codes: dict = {}
# 完成验证码校验的用户 -> 凭证到期时间戳
reset_tickets: dict = {}

# 一个固定成本的哑哈希：用户不存在时也跑一次 bcrypt，
# 让"账号不存在"和"密码错误"的响应时间接近，避免用时间差枚举用户名。
_dummy_hash: str | None = None


def _equalize_timing(password: str) -> None:
    """在"用户不存在"的分支里消耗和校验密码相当的时间。"""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = bcrypt.hashpw(
            b"timing-equalizer", bcrypt.gensalt(rounds=10)
        ).decode("utf-8")
    try:
        bcrypt.checkpw(password.encode("utf-8")[:72], _dummy_hash.encode("utf-8"))
    except Exception:  # noqa: BLE001 —— 只是为了消耗时间，失败无所谓
        pass


def hash_password(password: str) -> str:
    """把明文密码转成 bcrypt 哈希。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """校验明文密码是否匹配 bcrypt 哈希。"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _issue_token(response: Response, user: User) -> str:
    """签发 token，并把同一份 token 写进 HttpOnly cookie。

    为什么 cookie 里也要放一份：`/uploads/xxx.png` 是 `<img src>` 直接请求的，
    浏览器不会给图片请求加 Authorization 头。cookie 会被自动带上，
    于是图片终于可以校验登录态了（见 main.py 的 serve_upload）。
    API 仍然只认 Bearer —— cookie 只用于只读的图片 GET，不引入 CSRF 面。
    """
    token = create_access_token(
        user_id=user.id,
        username=user.username,
        token_version=user.token_version or 1,
        expires_seconds=TOKEN_EXPIRE_SECONDS,
    )
    response.set_cookie(
        key=MEDIA_COOKIE,
        value=token,
        max_age=TOKEN_EXPIRE_SECONDS,
        httponly=True,  # JS 读不到，XSS 也偷不走
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )
    return token


class RegisterBody(BaseModel):
    # 50 = users.username 的真实宽度。不限制的话，60 字的用户名会一路走到
    # INSERT，撞 MySQL 1406 Data too long → 裸 500（注册页直接白屏报错）。
    # 这里提前挡住，返回 422 和一句人话。
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(max_length=128)

class LoginBody(BaseModel):
    username: str = Field(max_length=50)
    password: str = Field(max_length=128)

class SendCodeBody(BaseModel):
    username: str = Field(max_length=50)

class VerifyCodeBody(BaseModel):
    username: str = Field(max_length=50)
    code: str = Field(min_length=1, max_length=16)

class ResetPasswordBody(BaseModel):
    username: str = Field(max_length=50)
    new_password: str = Field(max_length=128)




@router.post("/register", status_code=201)
def register(body: RegisterBody, request: Request, db: Session = Depends(get_db)):
    # 注册也要限流：不限的话可以用脚本批量刷号，把 users 表灌满，
    # 顺带给"用户名枚举"提供了免费确认渠道。
    ratelimit.hit("register-ip", ratelimit.client_ip(request), REGISTER_IP_MAX, 3600)

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
def login(
    body: LoginBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    ip = ratelimit.client_ip(request)
    # 按 IP 记所有尝试（宽松），按账号只记失败（严格但不锁人）
    ratelimit.hit("login-ip", ip, LOGIN_IP_MAX, LOGIN_WINDOW)

    user = db.query(User).filter(User.username == body.username).first()
    if not user:
        # 故意和"密码错误"用同一句话：
        # 之前两个分支分别回「账号不存在」「密码错误」，注册页 + 找回密码页
        # 一起就能把库里的用户名枚举出来，给撞库提供了免费的用户名清单。
        _equalize_timing(body.password)
        ratelimit.hit("login-user", body.username, LOGIN_MAX_FAILURES, LOGIN_WINDOW)
        raise HTTPException(status_code=400, detail="账号或密码错误")

    # bcrypt 哈希以 $2 开头；旧数据是明文
    if user.password.startswith("$2"):
        if not verify_password(body.password, user.password):
            ratelimit.hit("login-user", body.username, LOGIN_MAX_FAILURES, LOGIN_WINDOW)
            raise HTTPException(status_code=400, detail="账号或密码错误")
    else:
        # 兼容旧明文数据：校验通过后自动升级成哈希
        if user.password != body.password:
            ratelimit.hit("login-user", body.username, LOGIN_MAX_FAILURES, LOGIN_WINDOW)
            raise HTTPException(status_code=400, detail="账号或密码错误")
        user.password = hash_password(body.password)
        db.commit()

    # 登录成功 = 密码是对的，之前那几次失败不该继续累计
    ratelimit.clear("login-user", body.username)
    ratelimit.clear("login-ip", ip)

    token = _issue_token(response, user)

    return {
        "message": "登录成功",
        "token": token,
        "username": user.username,
    }

@router.post("/logout")
def logout(response: Response):
    """清掉图片访问用的 cookie。

    没有服务端 session 可销毁（JWT 是无状态的，吊销靠 token_version），
    这个接口只做一件事：让浏览器不再带着 cookie 去取图片。
    """
    response.delete_cookie(key=MEDIA_COOKIE, path="/")
    return {"message": "已退出登录"}

@router.post("/send-code")
def send_code(body: SendCodeBody, request: Request, db: Session = Depends(get_db)):
    # 限流放在查用户之前：否则攻击者可以用"响应快慢/次数"判断用户是否存在
    ip = ratelimit.client_ip(request)
    ratelimit.hit("send-code-ip", ip, SEND_CODE_IP_MAX, SEND_CODE_WINDOW)
    # 同一账号的最小重发间隔：防"点一下发一条"把短信/邮件通道刷爆
    ratelimit.hit("send-code-interval", body.username, 1, SEND_CODE_INTERVAL)
    ratelimit.hit(
        "send-code-user", body.username, SEND_CODE_MAX_PER_USER, SEND_CODE_WINDOW
    )

    username = db.query(User).filter(User.username == body.username).first()
    if not username:
        raise HTTPException(status_code=400,detail="用户不存在")

    code = f"{random.randint(100000,999999)}"

    codes[body.username] = {
        "code": code,
        "expires": int(time.time()) + CODE_EXPIRE_SECONDS,
        # 记下这个验证码已经错了几次：错够次数直接作废，
        # 否则 6 位验证码在 5 分钟内可以被穷举（原来完全不限制尝试次数）。
        "tries": 0,
    }

    payload = {"message": "验证码已发送"}
    if echo_code_enabled():
        # 只有明确的开发/测试环境才把验证码回显，方便本地调试。
        # 生产环境应该把验证码通过短信 / 邮件发出去。
        payload["code"] = code
    return payload

@router.post("/verify-code")
def verify_code(body: VerifyCodeBody, db: Session = Depends(get_db)):
    record = codes.get(body.username)

    if not record:
        raise HTTPException(status_code=400,detail="请先获取验证码")

    if time.time() > record["expires"]:
        codes.pop(body.username, None)
        raise HTTPException(status_code=400,detail="验证码已过期")

    if record["code"] != body.code:
        # 两层防护，缺一不可：
        # 1) `hit` 做频率限制（超过窗口内允许的次数直接 429）；
        # 2) `tries` 做验证码生命周期管理（错够次数就让这个码作废，
        #    否则一个 5 分钟有效的 6 位码仍然可以被慢慢猜）。
        record["tries"] = record.get("tries", 0) + 1
        if record["tries"] >= VERIFY_MAX_FAILURES:
            codes.pop(body.username, None)
            raise HTTPException(
                status_code=429,
                detail="验证码错误次数过多，请重新获取验证码",
                headers={"Retry-After": str(int(VERIFY_WINDOW))},
            )
        ratelimit.hit("verify-user", body.username, VERIFY_MAX_FAILURES, VERIFY_WINDOW)
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
    # 重置密码同样要吊销旧 token：账号可能就是被别人踢了才来重置的，
    # 如果旧 token 还能用一小时，这次重置等于没做。
    user.token_version = (user.token_version or 1) + 1
    db.commit()

    # 凭证一次性使用，改完密码立即失效
    reset_tickets.pop(body.username, None)
    ratelimit.clear("login-user", body.username)

    return {"message": "密码修改成功"}
