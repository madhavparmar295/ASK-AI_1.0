from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models.user import User, OTP
from schemas.auth import (
    UserRegister,
    UserLogin,
    OTPVerify,
    OTPResend,
    UserOut,
    TokenResponse,
    GenericResponse,
)
from services.security import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
)
from services.mailer import send_otp_email

router = APIRouter(prefix="/auth", tags=["User Authentication & OTP"])


@router.post(
    "/register",
    response_model=GenericResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user and send verification OTP",
)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    """
    Registers a new account.
    - If user exists and is already verified, returns 400.
    - If user exists but is unverified, updates password, issues a new OTP and resends email.
    - If user does not exist, creates User (is_verified=False), issues OTP, and emails code.
    """
    email = payload.email.lower().strip()
    existing_user = db.query(User).filter(User.email == email).first()

    if existing_user:
        if existing_user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email already exists and is verified.",
            )
        # Unverified user retrying registration - update password and generate new OTP
        existing_user.hashed_password = hash_password(payload.password)
        db.commit()
        otp = OTP.generate_for_user(db, existing_user)
        send_otp_email(existing_user.email, otp.code, otp.OTP_VALIDITY_MINUTES)
        return GenericResponse(
            status="success",
            message="Account exists but unverified. A new verification code has been emailed to you.",
        )

    # Create new unverified user
    new_user = User(
        email=email,
        hashed_password=hash_password(payload.password),
        is_verified=False,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Generate OTP and email it
    otp = OTP.generate_for_user(db, new_user)
    send_otp_email(new_user.email, otp.code, otp.OTP_VALIDITY_MINUTES)

    return GenericResponse(
        status="success",
        message="Registration successful! We have emailed you a 6-digit verification code.",
    )


@router.post(
    "/verify-otp",
    response_model=TokenResponse,
    summary="Verify 6-digit OTP code and authenticate user",
)
def verify_otp(payload: OTPVerify, db: Session = Depends(get_db)):
    """
    Verifies the email OTP.
    - Supports the universal test bypass code ('339876') matching Django's behavior.
    - Marks user as verified and OTP as used.
    - Returns JWT access token immediately so the user is authenticated without re-typing password.
    """
    email = payload.email.lower().strip()
    code = payload.code.strip()

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found with this email address.",
        )

    # Universal bypass code for automated tests & quick QA
    if code == OTP.TEST_BYPASS_CODE:
        user.is_verified = True
        db.commit()
        db.refresh(user)
        token = create_access_token(data={"sub": user.email, "user_id": user.id})
        return TokenResponse(access_token=token, token_type="bearer", user=user)

    # Find the most recent OTP for user matching the code
    otp = (
        db.query(OTP)
        .filter(OTP.user_id == user.id, OTP.code == code)
        .order_by(OTP.created_at.desc())
        .first()
    )

    if otp is None or not otp.is_valid():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code.",
        )

    # Mark OTP as used and user as verified
    otp.is_used = True
    user.is_verified = True
    db.commit()
    db.refresh(user)

    token = create_access_token(data={"sub": user.email, "user_id": user.id})
    return TokenResponse(access_token=token, token_type="bearer", user=user)


@router.post(
    "/resend-otp",
    response_model=GenericResponse,
    summary="Resend verification OTP email",
)
def resend_otp(payload: OTPResend, db: Session = Depends(get_db)):
    """
    Invalidates any previous unused OTP and sends a new one to the user's email.
    """
    email = payload.email.lower().strip()
    user = db.query(User).filter(User.email == email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found with this email address.",
        )

    if user.is_verified:
        return GenericResponse(
            status="info",
            message="Your account is already verified. You can log in directly.",
        )

    otp = OTP.generate_for_user(db, user)
    send_otp_email(user.email, otp.code, otp.OTP_VALIDITY_MINUTES)

    return GenericResponse(
        status="success",
        message="A fresh verification code has been sent to your email.",
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in with email and password",
)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    """
    Authenticates email and password.
    - If user is unverified, denies login with 403 and prompts to verify OTP first.
    - If valid, returns JWT access token.
    """
    email = payload.email.lower().strip()
    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not verified. Please verify the OTP sent to your email first.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is disabled.",
        )

    token = create_access_token(data={"sub": user.email, "user_id": user.id})
    return TokenResponse(access_token=token, token_type="bearer", user=user)


@router.get(
    "/me",
    response_model=UserOut,
    summary="Get current logged in user details",
)
def get_me(current_user: User = Depends(get_current_user)):
    """
    Protected endpoint to test and retrieve current authenticated user.
    Requires Bearer <access_token> in the Authorization header.
    """
    return current_user
