"""
SQLAlchemy Base Model

共通のベースモデルを定義
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Column, DateTime, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class TimestampMixin:
    """タイムスタンプ共通カラム"""

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=datetime.utcnow,
        nullable=True,
    )


def generate_uuid():
    """UUID生成"""
    return str(uuid4())
