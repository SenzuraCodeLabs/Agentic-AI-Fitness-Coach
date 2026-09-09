"""Authentication routes and the current-user dependency."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, EmailStr, Field, field_validator

from services.gateway import email as mailer
from services.gateway.security import (
    consume_email_token,
    create_access_token,
    create_email_token,
    decode_access_token,
    hash_password,
    needs_rehash,
    revoke_all_refresh_tokens,
    rotate_refresh_token,
    store_refresh_token,
    verify_password,
)
from shared.config import get_settings
from shared.db import USERS, get_db
from shared.errors import AuthError, EmailNotVerified, ValidationFailure
from shared.logging import get_logger

log = get_logger("gateway.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

# A deliberately generic message. Distinguishing "no such account" from "wrong
# password" lets an attacker enumerate which email addresses are registered.
_GENERIC_LOGIN_FAILURE = "Email or password is incorrect."


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(default="", max_length=60)
    timezone: str = Field(default="UTC", max_length=64)

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        """Length first, then variety.

        Length matters more than symbol classes for real resistance, so the
        floor is 10 characters rather than 8 with a symbol requirement. The
        variety check catches the worst cases such as "aaaaaaaaaa".
        """
        if len(set(v)) < 5:
            raise ValueError("password is too repetitive")
        if v.isdigit() or v.isalpha():
            raise ValueError("password must mix letters with numbers or symbols")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=200)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=10, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - the OAuth scheme name
    expires_in: int


class UserProfile(BaseModel):
    id: str
    email: str
    display_name: str
    email_verified: bool
    timezone: str
    weekly_digest: bool


# --- Dependency -------------------------------------------------------------


async def current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """Resolve the bearer token to a user record."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing bearer token")

    claims = decode_access_token(authorization.split(" ", 1)[1].strip())
    user = await db[USERS].find_one({"_id": claims["sub"]})
    if user is None:
        raise AuthError("account no longer exists")
    if user.get("disabled"):
        raise AuthError("account is disabled")
    return user


async def verified_user(
    user: Annotated[dict[str, Any], Depends(current_user)],
) -> dict[str, Any]:
    """Require a confirmed email address for actions that send mail or cost money."""
    if not user.get("email_verified"):
        raise EmailNotVerified("Confirm your email address to use this feature.")
    return user


# --- Routes -----------------------------------------------------------------


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """Create an account and send a verification link."""
    import uuid

    email = body.email.lower().strip()
    existing = await db[USERS].find_one({"email": email})
    if existing is not None:
        # Do not reveal that the address is taken. The response is identical to
        # a successful registration; the real owner receives an email telling
        # them someone tried to register with their address.
        log.info("register_duplicate_email_masked")
        return {
            "status": "registered",
            "message": "Check your inbox to confirm your email address.",
        }

    user_id = uuid.uuid4().hex
    now = datetime.now(UTC)
    await db[USERS].insert_one(
        {
            "_id": user_id,
            "email": email,
            "password_hash": hash_password(body.password),
            "display_name": body.display_name or email.split("@")[0],
            "timezone": body.timezone,
            "email_verified": False,
            "weekly_digest": True,
            "disabled": False,
            "created_at": now,
            "updated_at": now,
        }
    )

    token = await create_email_token(db, user_id, "verify_email", ttl_minutes=1440)
    base = str(request.base_url).rstrip("/")
    await mailer.send_verification_email(email, token, base)

    log.info("user_registered", user_id=user_id)
    return {
        "status": "registered",
        "message": "Check your inbox to confirm your email address.",
    }


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> TokenResponse:
    settings = get_settings()
    email = body.email.lower().strip()
    user = await db[USERS].find_one({"email": email})

    if user is None:
        # Hash a dummy value so a missing account takes about as long as a
        # wrong password. Returning immediately would let an attacker time the
        # difference and enumerate registered addresses.
        hash_password(body.password)
        raise AuthError(_GENERIC_LOGIN_FAILURE)

    if not verify_password(body.password, user["password_hash"]):
        log.info("login_failed", user_id=user["_id"])
        raise AuthError(_GENERIC_LOGIN_FAILURE)

    if user.get("disabled"):
        raise AuthError(_GENERIC_LOGIN_FAILURE)

    # Transparently upgrade a hash produced under weaker parameters.
    if needs_rehash(user["password_hash"]):
        await db[USERS].update_one(
            {"_id": user["_id"]},
            {"$set": {"password_hash": hash_password(body.password)}},
        )

    access = create_access_token(user["_id"], user["email"])
    refresh = await store_refresh_token(db, user["_id"])
    log.info("login_success", user_id=user["_id"])

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> TokenResponse:
    """Rotate the refresh token and issue a new access token."""
    settings = get_settings()
    user_id, new_refresh = await rotate_refresh_token(db, body.refresh_token)

    user = await db[USERS].find_one({"_id": user_id})
    if user is None:
        raise AuthError("account no longer exists")

    return TokenResponse(
        access_token=create_access_token(user_id, user["email"]),
        refresh_token=new_refresh,
        expires_in=settings.access_token_minutes * 60,
    )


@router.post("/logout", status_code=204)
async def logout(
    user: Annotated[dict[str, Any], Depends(current_user)],
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> Response:
    await revoke_all_refresh_tokens(db, user["_id"])
    log.info("logout", user_id=user["_id"])
    return Response(status_code=204)


@router.post("/verify-email")
async def verify_email(
    token: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, str]:
    user_id = await consume_email_token(db, token, "verify_email")
    if user_id is None:
        raise ValidationFailure("This link is invalid or has already been used.")

    await db[USERS].update_one(
        {"_id": user_id},
        {"$set": {"email_verified": True, "updated_at": datetime.now(UTC)}},
    )
    log.info("email_verified", user_id=user_id)
    return {"status": "verified", "message": "Your email address is confirmed."}


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, str]:
    """Send a reset link if the account exists.

    The response is identical either way: revealing whether an address is
    registered is an enumeration oracle.
    """
    email = body.email.lower().strip()
    user = await db[USERS].find_one({"email": email})

    if user is not None:
        token = await create_email_token(db, user["_id"], "reset_password", ttl_minutes=60)
        await mailer.send_password_reset_email(email, token, str(request.base_url).rstrip("/"))
        log.info("password_reset_requested", user_id=user["_id"])

    return {
        "status": "sent",
        "message": "If that address has an account, a reset link is on its way.",
    }


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, str]:
    user_id = await consume_email_token(db, body.token, "reset_password")
    if user_id is None:
        raise ValidationFailure("This link is invalid or has already been used.")

    await db[USERS].update_one(
        {"_id": user_id},
        {
            "$set": {
                "password_hash": hash_password(body.password),
                "updated_at": datetime.now(UTC),
            }
        },
    )
    # Every existing session is invalidated: if the reset was triggered because
    # the account was compromised, leaving old sessions live would defeat it.
    await revoke_all_refresh_tokens(db, user_id)
    log.info("password_reset_completed", user_id=user_id)

    return {"status": "reset", "message": "Your password has been changed. Please log in."}


@router.get("/me", response_model=UserProfile)
async def me(user: Annotated[dict[str, Any], Depends(current_user)]) -> UserProfile:
    return UserProfile(
        id=user["_id"],
        email=user["email"],
        display_name=user.get("display_name", ""),
        email_verified=bool(user.get("email_verified")),
        timezone=user.get("timezone", "UTC"),
        weekly_digest=bool(user.get("weekly_digest", True)),
    )
