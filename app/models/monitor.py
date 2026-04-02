from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Enum as SAEnum, ForeignKey, Text  # noqa: F401
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base
import enum


class MonitorType(str, enum.Enum):
    http = "http"
    https = "https"
    ping = "ping"
    port = "port"
    keyword = "keyword"


class MonitorStatus(str, enum.Enum):
    up = "up"
    down = "down"
    paused = "paused"
    pending = "pending"


class Monitor(Base):
    __tablename__ = "monitors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    type = Column(SAEnum(MonitorType), nullable=False)
    url = Column(String(500), nullable=False)
    port = Column(Integer, nullable=True)
    group_id = Column(Integer, ForeignKey("monitor_groups.id"), nullable=True)
    keyword = Column(String(255), nullable=True)
    interval = Column(Integer, default=300)
    timeout = Column(Integer, default=30)
    http_method = Column(String(10), default="GET")
    follow_redirects = Column(Boolean, default=True)
    status = Column(SAEnum(MonitorStatus), default=MonitorStatus.pending)
    is_active = Column(Boolean, default=True)
    last_checked_at = Column(DateTime, nullable=True)
    last_response_time = Column(Float, nullable=True)
    uptime_percentage = Column(Float, default=100.0)
    notification_email = Column(String(255), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    creator = relationship("User", back_populates="monitors")
    group = relationship("MonitorGroup", back_populates="monitors")
    logs = relationship("MonitorLog", back_populates="monitor", cascade="all, delete-orphan", order_by="desc(MonitorLog.checked_at)")
    incidents = relationship("Incident", back_populates="monitor", cascade="all, delete-orphan", order_by="desc(Incident.started_at)")
