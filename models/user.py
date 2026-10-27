import random
from datetime import datetime, timedelta, timezone
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    """User account model matching the original Django fields."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    otps = relationship("OTP", back_populates="user", cascade="all, delete-orphan", order_by="desc(OTP.created_at)")

    def __repr__(self):
        return f"<User id={self.id} email={self.email} verified={self.is_verified}>"


class OTP(Base):
    """
    One-time password tied to a user for email verification.
    Preserves exact Django verification rules:
    - 6-digit numeric code
    - 10-minute validity
    - Older unused OTPs invalidated when new one generated
    - Universal test bypass code '339876'
    """
    __tablename__ = "otps"

    OTP_LENGTH = 6
    OTP_VALIDITY_MINUTES = 10
    TEST_BYPASS_CODE = "339876"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(6), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False)

    user = relationship("User", back_populates="otps")

    @classmethod
    def generate_for_user(cls, db, user: User):
        """
        Creates a fresh OTP for the user and invalidates any earlier unused OTPs.
        """
        # Invalidate earlier unused codes
        db.query(cls).filter(cls.user_id == user.id, cls.is_used == False).update({"is_used": True})
        
        # Generate new 6-digit code
        code = "".join(random.choices("0123456789", k=cls.OTP_LENGTH))
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=cls.OTP_VALIDITY_MINUTES)

        otp = cls(user_id=user.id, code=code, expires_at=expires_at, is_used=False)
        db.add(otp)
        db.commit()
        db.refresh(otp)
        return otp

    def is_valid(self) -> bool:
        """Checks if the OTP is unused and not expired."""
        if self.is_used:
            return False
        # Normalize timezone awareness
        now = datetime.now(timezone.utc)
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return now <= exp
