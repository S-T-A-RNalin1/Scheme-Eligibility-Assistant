"""Password hashing (PBKDF2-SHA256), JWT tokens and role-based FastAPI dependencies."""
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from bson import ObjectId
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config
from .db import get_db

ITERATIONS = 240_000
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
    return hmac.compare_digest(dk.hex(), digest)


def make_token(user: dict) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=config.JWT_TTL_MINUTES)
    return jwt.encode({"sub": str(user["_id"]), "role": user["role"], "exp": exp}, config.JWT_SECRET, algorithm="HS256")


def optional_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict | None:
    if not creds:
        return None
    try:
        payload = jwt.decode(creds.credentials, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = get_db().users.find_one({"_id": ObjectId(payload["sub"])}, {"password_hash": 0})
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return user


def require_user(user: dict | None = Depends(optional_user)) -> dict:
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login required")
    return user


def require_admin(user: dict = Depends(require_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user
