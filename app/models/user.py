from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum as SAEnum
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base
import enum


class UserRole(str, enum.Enum):
    admin = "admin"
    editor = "editor"
    readonly = "readonly"


class AuthProvider(str, enum.Enum):
    local = "local"
    saml = "saml"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(150), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    display_name = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=True)
    role = Column(SAEnum(UserRole), default=UserRole.readonly, nullable=False)
    auth_provider = Column(SAEnum(AuthProvider), default=AuthProvider.local, nullable=False)
    must_change_password = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    theme = Column(String(10), default="dark", nullable=False, server_default="dark")
    sidebar_pinned = Column(Boolean, default=True, nullable=False, server_default="1")
    timezone_offset = Column(Integer, default=3, nullable=False, server_default="3")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    monitors = relationship("Monitor", back_populates="creator")
