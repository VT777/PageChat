import re
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, validator
import aiosqlite
import jwt
import bcrypt

from app.models.database import get_db
from app.core.config import DATA_DIR

router = APIRouter(prefix="/api/auth", tags=["authentication"])

# JWT 配置
JWT_SECRET = secrets.token_hex(32)  # 生成随机密钥
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = 7

# 安全依赖
security = HTTPBearer(auto_error=False)


# 安全配置
LOGIN_FAIL_LIMIT = 5  # 最大失败次数
LOCKOUT_DURATION = timedelta(minutes=15)  # 锁定时间


# 数据库操作的登录尝试记录
async def get_login_attempts(db: aiosqlite.Connection, email: str) -> Optional[dict]:
    """从数据库获取登录尝试记录"""
    async with db.execute(
        "SELECT email, count, locked_until, last_attempt FROM login_attempts WHERE email = ?",
        (email,),
    ) as cursor:
        row = await cursor.fetchone()
        if row:
            return {
                "email": row[0],
                "count": row[1],
                "locked_until": row[2],
                "last_attempt": row[3],
            }
        return None


async def update_login_attempts(
    db: aiosqlite.Connection, email: str, count: int, locked_until: datetime = None
):
    """更新登录尝试记录"""
    await db.execute(
        """INSERT INTO login_attempts (email, count, locked_until, last_attempt)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(email) DO UPDATE SET
           count = excluded.count,
           locked_until = excluded.locked_until,
           last_attempt = excluded.last_attempt""",
        (email, count, locked_until),
    )
    await db.commit()


async def clear_login_attempts(db: aiosqlite.Connection, email: str):
    """清除登录尝试记录"""
    await db.execute("DELETE FROM login_attempts WHERE email = ?", (email,))
    await db.commit()


# 登录日志记录
async def log_login_attempt(
    db: aiosqlite.Connection,
    email: str,
    success: bool,
    user_id: str = None,
    fail_reason: str = None,
    ip_address: str = None,
    user_agent: str = None,
):
    """记录登录日志"""
    await db.execute(
        """INSERT INTO login_logs (user_id, email, ip_address, user_agent, success, fail_reason)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, email, ip_address, user_agent, success, fail_reason),
    )
    await db.commit()


# 请求/响应模型
class UserRegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str

    @validator("username")
    def username_valid(cls, v):
        if len(v) < 3:
            raise ValueError("用户名至少3个字符")
        if not v.isalnum() and "_" not in v:
            raise ValueError("用户名只能包含字母、数字和下划线")
        return v


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    avatar: Optional[str] = None


class AuthResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    user: Optional[UserResponse] = None
    error: Optional[str] = None


# 密码工具函数
def hash_password(password: str) -> str:
    """使用 bcrypt 哈希密码"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(password: str, hashed: str) -> bool:
    """验证密码"""
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except:
        return False


def validate_password_strength(password: str) -> tuple[bool, str]:
    """验证密码强度"""
    if len(password) < 8:
        return False, "密码长度至少8位"
    if not re.search(r"[A-Z]", password):
        return False, "密码必须包含大写字母"
    if not re.search(r"[a-z]", password):
        return False, "密码必须包含小写字母"
    if not re.search(r"\d", password):
        return False, "密码必须包含数字"
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "密码必须包含特殊字符"
    return True, ""


def create_token(user_id: str) -> str:
    """创建 JWT token"""
    payload = {
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(days=JWT_EXPIRATION_DAYS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[str]:
    """验证 JWT token，返回 user_id"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("user_id")
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


async def check_login_attempts(
    db: aiosqlite.Connection, email: str
) -> tuple[bool, str]:
    """检查登录尝试次数，返回 (是否允许登录, 错误信息)"""
    attempt = await get_login_attempts(db, email)
    if not attempt:
        return True, ""

    if attempt["count"] >= LOGIN_FAIL_LIMIT:
        # 检查是否已过锁定期
        locked_until = attempt["locked_until"]
        if locked_until:
            try:
                # 处理 ISO 格式时间（带时区）
                locked_str = locked_until.replace("Z", "+00:00")
                locked_datetime = datetime.fromisoformat(locked_str)
            except ValueError:
                # 处理 SQLite 默认格式 "YYYY-MM-DD HH:MM:SS"
                try:
                    locked_datetime = datetime.strptime(locked_until, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    # 如果解析失败，清除记录
                    await clear_login_attempts(db, email)
                    return True, ""
            
            if datetime.utcnow() < locked_datetime:
                remaining = max(0, (locked_datetime - datetime.utcnow()).seconds // 60)
                return False, f"登录失败次数过多，请 {remaining} 分钟后重试"
        
        # 锁定期已过或无锁定期，重置计数
        await clear_login_attempts(db, email)
        return True, ""
    return True, ""


async def record_login_failure(db: aiosqlite.Connection, email: str):
    """记录登录失败"""
    attempt = await get_login_attempts(db, email)

    if not attempt:
        count = 1
        locked_until = None
    else:
        count = attempt["count"] + 1
        locked_until = None
        if count >= LOGIN_FAIL_LIMIT:
            locked_until = datetime.utcnow() + LOCKOUT_DURATION

    await update_login_attempts(db, email, count, locked_until)


async def record_login_success(db: aiosqlite.Connection, email: str):
    """记录登录成功，清除失败记录"""
    await clear_login_attempts(db, email)


# 依赖函数
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: aiosqlite.Connection = Depends(get_db),
) -> Optional[dict]:
    """获取当前登录用户"""
    if not credentials:
        return None

    user_id = verify_token(credentials.credentials)
    if not user_id:
        return None

    async with db.execute(
        "SELECT id, username, email, avatar FROM users WHERE id = ?", (user_id,)
    ) as cursor:
        row = await cursor.fetchone()
        if row:
            return dict(row)
    return None


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """要求必须登录"""
    user = await get_current_user(credentials, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或token已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# API 端点
@router.post("/register", response_model=AuthResponse)
async def register(
    request: UserRegisterRequest, db: aiosqlite.Connection = Depends(get_db)
):
    """用户注册"""
    # 验证密码强度
    is_valid, error_msg = validate_password_strength(request.password)
    if not is_valid:
        return AuthResponse(success=False, error=error_msg)

    # 检查邮箱是否已存在
    async with db.execute(
        "SELECT id FROM users WHERE email = ?", (request.email,)
    ) as cursor:
        if await cursor.fetchone():
            return AuthResponse(success=False, error="该邮箱已被注册")

    # 检查用户名是否已存在
    async with db.execute(
        "SELECT id FROM users WHERE username = ?", (request.username,)
    ) as cursor:
        if await cursor.fetchone():
            return AuthResponse(success=False, error="该用户名已被使用")

    # 创建用户
    user_id = str(uuid.uuid4())
    password_hash = hash_password(request.password)
    avatar = f"https://api.dicebear.com/7.x/avataaars/svg?seed={request.email}"

    await db.execute(
        """
        INSERT INTO users (id, username, email, password_hash, avatar)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, request.username, request.email, password_hash, avatar),
    )
    await db.commit()

    # 生成 token
    token = create_token(user_id)

    return AuthResponse(
        success=True,
        token=token,
        user=UserResponse(
            id=user_id, username=request.username, email=request.email, avatar=avatar
        ),
    )


@router.post("/login", response_model=AuthResponse)
async def login(request: UserLoginRequest, db: aiosqlite.Connection = Depends(get_db)):
    """用户登录"""
    try:
        # 检查登录尝试次数
        can_login, error_msg = await check_login_attempts(db, request.email)
        if not can_login:
            # 记录失败的登录尝试（锁定）
            await log_login_attempt(
                db,
                email=request.email,
                success=False,
                fail_reason=f"Account locked: {error_msg}",
            )
            return AuthResponse(success=False, error=error_msg)

        # 查找用户
        async with db.execute(
            "SELECT id, username, email, password_hash, avatar FROM users WHERE email = ?",
            (request.email,),
        ) as cursor:
            user = await cursor.fetchone()

        if not user:
            await record_login_failure(db, request.email)
            await log_login_attempt(
                db, email=request.email, success=False, fail_reason="User not found"
            )
            return AuthResponse(success=False, error="邮箱或密码错误")

        # 验证密码
        if not verify_password(request.password, user["password_hash"]):
            await record_login_failure(db, request.email)
            await log_login_attempt(
                db, email=request.email, success=False, fail_reason="Invalid password"
            )
            return AuthResponse(success=False, error="邮箱或密码错误")

        # 登录成功，清除失败记录
        await record_login_success(db, request.email)

        # 记录成功登录
        await log_login_attempt(db, user_id=user["id"], email=request.email, success=True)

        # 生成 token
        token = create_token(user["id"])

        return AuthResponse(
            success=True,
            token=token,
            user=UserResponse(
                id=user["id"],
                username=user["username"],
                email=user["email"],
                avatar=user["avatar"],
            ),
        )
    except Exception as e:
        import traceback
        print(f"[Login Error] {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"登录失败: {str(e)}")


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(require_auth)):
    """获取当前用户信息"""
    return UserResponse(
        id=current_user["id"],
        username=current_user["username"],
        email=current_user["email"],
        avatar=current_user.get("avatar"),
    )


@router.post("/logout")
async def logout():
    """用户登出（前端清除token即可）"""
    return {"success": True, "message": "已登出"}


@router.get("/verify")
async def verify_token_endpoint(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """验证token是否有效"""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供token"
        )

    user_id = verify_token(credentials.credentials)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token无效或已过期"
        )

    return {"valid": True, "user_id": user_id}
