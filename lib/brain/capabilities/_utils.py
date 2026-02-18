"""
lib.brain.capabilities._utils — UUID変換共有ユーティリティ

capabilities/ 配下の各モジュールで共通して使用する
UUID変換ヘルパー関数。
"""

from typing import Optional
from uuid import UUID


def parse_org_uuid(org_id: str) -> UUID:
    """org_id文字列をUUIDに変換するヘルパー

    UUID形式でない場合はuuid5で決定論的に変換する。
    """
    if isinstance(org_id, UUID):
        return org_id
    try:
        return UUID(org_id)
    except (ValueError, TypeError, AttributeError):
        import uuid as uuid_mod
        return uuid_mod.uuid5(uuid_mod.NAMESPACE_OID, str(org_id))


def safe_parse_uuid(value) -> Optional[UUID]:
    """文字列をUUIDに安全に変換するヘルパー

    ChatworkのアカウントIDなど、UUID形式でない場合はuuid5で変換する。
    """
    if not value:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        import uuid as uuid_mod
        return uuid_mod.uuid5(uuid_mod.NAMESPACE_OID, str(value))
