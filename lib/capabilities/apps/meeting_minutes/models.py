# lib/capabilities/apps/meeting_minutes/models.py
"""
App1: 議事録自動生成 - データモデル

Author: Claude Opus 4.5
Created: 2026-01-27
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4

from .constants import MeetingType, MinutesStatus, MinutesSection


# =============================================================================
# 入力モデル
# =============================================================================


@dataclass
class MeetingMinutesRequest:
    """
    議事録生成リクエスト

    音声ファイルから議事録を生成するためのリクエスト。
    """
    # 必須項目
    organization_id: UUID

    # 音声入力（いずれか必須）
    audio_data: Optional[bytes] = None
    audio_file_path: Optional[str] = None
    audio_url: Optional[str] = None

    # 会議情報（オプション）
    meeting_title: Optional[str] = None  # 省略時は自動生成
    meeting_type: MeetingType = MeetingType.UNKNOWN  # 省略時は自動判定
    meeting_date: Optional[datetime] = None
    attendees: List[str] = field(default_factory=list)  # 既知の参加者

    # 生成設定
    instruction: str = ""  # 追加指示（例: 「技術用語を詳しく」）
    language: str = "ja"
    detect_speakers: bool = True
    generate_action_items: bool = True

    # 出力設定
    output_to_google_docs: bool = True
    target_folder_id: Optional[str] = None
    share_with: List[str] = field(default_factory=list)

    # 確認設定
    require_confirmation: bool = False  # 生成前に確認するか

    # メタデータ
    user_id: Optional[UUID] = None
    request_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "request_id": self.request_id,
            "organization_id": str(self.organization_id),
            "has_audio_data": self.audio_data is not None,
            "audio_file_path": self.audio_file_path,
            "meeting_title": self.meeting_title,
            "meeting_type": self.meeting_type.value,
            "meeting_date": self.meeting_date.isoformat() if self.meeting_date else None,
            "attendees_count": len(self.attendees),
            "instruction": self.instruction[:100] if self.instruction else "",
            "language": self.language,
            "detect_speakers": self.detect_speakers,
            "generate_action_items": self.generate_action_items,
            "output_to_google_docs": self.output_to_google_docs,
            "require_confirmation": self.require_confirmation,
            "user_id": str(self.user_id) if self.user_id else None,
            "created_at": self.created_at.isoformat(),
        }


# =============================================================================
# 中間モデル
# =============================================================================


@dataclass
class ActionItem:
    """アクションアイテム"""
    task: str
    assignee: Optional[str] = None
    deadline: Optional[str] = None
    priority: str = "normal"  # high, normal, low

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "assignee": self.assignee,
            "deadline": self.deadline,
            "priority": self.priority,
        }

    def to_markdown(self) -> str:
        """Markdown形式で出力"""
        parts = [f"- [ ] {self.task}"]
        if self.assignee:
            parts.append(f"（担当: {self.assignee}）")
        if self.deadline:
            parts.append(f"【期限: {self.deadline}】")
        return " ".join(parts)


@dataclass
class Decision:
    """決定事項"""
    content: str
    context: Optional[str] = None
    decided_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "context": self.context,
            "decided_by": self.decided_by,
        }

    def to_markdown(self) -> str:
        return f"- ✅ {self.content}"


@dataclass
class DiscussionTopic:
    """議論トピック"""
    topic: str
    summary: str
    speakers: List[str] = field(default_factory=list)
    key_points: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "summary": self.summary,
            "speakers": self.speakers,
            "key_points": self.key_points,
        }

    def to_markdown(self) -> str:
        lines = [f"### {self.topic}", "", self.summary]
        if self.key_points:
            lines.append("")
            for point in self.key_points:
                lines.append(f"- {point}")
        return "\n".join(lines)


@dataclass
class MeetingAnalysis:
    """
    会議分析結果

    文字起こしから抽出した会議情報。
    """
    # 基本情報
    meeting_title: str = ""
    meeting_date: Optional[str] = None
    duration_estimate: Optional[str] = None
    meeting_type: MeetingType = MeetingType.UNKNOWN

    # 参加者
    attendees: List[str] = field(default_factory=list)
    speaker_mapping: Dict[str, str] = field(default_factory=dict)  # 話者ID → 名前

    # 内容
    main_topics: List[str] = field(default_factory=list)
    discussions: List[DiscussionTopic] = field(default_factory=list)
    decisions: List[Decision] = field(default_factory=list)
    action_items: List[ActionItem] = field(default_factory=list)

    # その他
    next_meeting: Optional[str] = None
    notes: str = ""

    # メタデータ
    analysis_confidence: float = 0.0
    tokens_used: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "meeting_title": self.meeting_title,
            "meeting_date": self.meeting_date,
            "duration_estimate": self.duration_estimate,
            "meeting_type": self.meeting_type.value,
            "attendees": self.attendees,
            "speaker_mapping": self.speaker_mapping,
            "main_topics": self.main_topics,
            "discussions": [d.to_dict() for d in self.discussions],
            "decisions": [d.to_dict() for d in self.decisions],
            "action_items": [a.to_dict() for a in self.action_items],
            "next_meeting": self.next_meeting,
            "notes": self.notes,
            "analysis_confidence": self.analysis_confidence,
        }


# =============================================================================
# 出力モデル
# =============================================================================


@dataclass
class MeetingMinutesResult:
    """
    議事録生成結果
    """
    # ステータス
    status: MinutesStatus = MinutesStatus.PROCESSING
    success: bool = False

    # 文字起こし結果
    transcript: str = ""
    transcript_segments: int = 0
    speakers_detected: int = 0
    audio_duration_seconds: float = 0.0

    # 分析結果
    analysis: Optional[MeetingAnalysis] = None

    # 生成された議事録
    minutes_content: str = ""  # Markdown形式
    minutes_word_count: int = 0

    # Google Docs出力
    document_id: Optional[str] = None
    document_url: Optional[str] = None

    # メタデータ
    request_id: str = ""
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    processing_time_ms: Optional[int] = None
    total_tokens_used: int = 0
    estimated_cost_jpy: float = 0.0

    # エラー情報
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    def complete(self, success: bool = True) -> "MeetingMinutesResult":
        """処理完了"""
        self.completed_at = datetime.utcnow()
        if self.started_at:
            delta = self.completed_at - self.started_at
            self.processing_time_ms = int(delta.total_seconds() * 1000)
        self.success = success
        if success:
            self.status = MinutesStatus.COMPLETED
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "success": self.success,
            "transcript_length": len(self.transcript),
            "transcript_segments": self.transcript_segments,
            "speakers_detected": self.speakers_detected,
            "audio_duration_seconds": self.audio_duration_seconds,
            "has_analysis": self.analysis is not None,
            "minutes_word_count": self.minutes_word_count,
            "document_id": self.document_id,
            "document_url": self.document_url,
            "request_id": self.request_id,
            "processing_time_ms": self.processing_time_ms,
            "total_tokens_used": self.total_tokens_used,
            "estimated_cost_jpy": self.estimated_cost_jpy,
            "error_message": self.error_message,
            "error_code": self.error_code,
        }

    def to_user_message(self) -> str:
        """ユーザー向けメッセージを生成"""
        if self.status == MinutesStatus.PROCESSING:
            return "議事録を作成中ウル... 🎙️"

        if self.status == MinutesStatus.TRANSCRIBING:
            return "音声を文字起こし中ウル... 📝"

        if self.status == MinutesStatus.ANALYZING:
            return "会議内容を分析中ウル... 🔍"

        if self.status == MinutesStatus.GENERATING:
            return "議事録を生成中ウル... ✍️"

        if self.status == MinutesStatus.PENDING and self.analysis:
            lines = [
                "会議を分析したウル！",
                "",
                f"📋 **{self.analysis.meeting_title or '会議'}**",
                f"👥 参加者: {len(self.analysis.attendees)}名",
                f"📌 議題: {len(self.analysis.main_topics)}件",
                f"✅ 決定事項: {len(self.analysis.decisions)}件",
                f"📝 アクションアイテム: {len(self.analysis.action_items)}件",
                "",
                "この内容で議事録を作成していいウル？",
            ]
            return "\n".join(lines)

        if self.status == MinutesStatus.COMPLETED:
            lines = [
                "━━━━━━━━━━━━━━━━━━━━━━",
                "✅ 議事録が完成したウル！",
                "",
            ]
            if self.analysis:
                lines.append(f"📋 {self.analysis.meeting_title or '会議議事録'}")
            if self.document_url:
                lines.append(f"🔗 {self.document_url}")
            lines.extend([
                "",
                f"⏱️ 音声時間: {self._format_duration(self.audio_duration_seconds)}",
                f"👥 検出話者: {self.speakers_detected}名",
                f"📝 文字数: {self.minutes_word_count:,}文字",
                f"💰 コスト: ¥{self.estimated_cost_jpy:.0f}",
                "",
                "内容を確認して、修正があれば教えてウル！",
                "━━━━━━━━━━━━━━━━━━━━━━",
            ])
            return "\n".join(lines)

        if self.status == MinutesStatus.FAILED:
            return f"議事録の作成に失敗したウル... 😢\n{self.error_message or '原因不明'}"

        return f"処理中ウル...（{self.status.value}）"

    def _format_duration(self, seconds: float) -> str:
        """秒を読みやすい形式に変換"""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        if minutes >= 60:
            hours = minutes // 60
            mins = minutes % 60
            return f"{hours}時間{mins}分"
        return f"{minutes}分{secs}秒"

    def to_brain_context(self) -> str:
        """脳のコンテキスト用文字列を生成"""
        lines = ["【議事録生成結果】"]
        lines.append(f"ステータス: {self.status.value}")

        if self.analysis:
            lines.append(f"タイトル: {self.analysis.meeting_title}")
            lines.append(f"参加者: {', '.join(self.analysis.attendees[:5])}")
            if len(self.analysis.attendees) > 5:
                lines.append(f"  他{len(self.analysis.attendees) - 5}名")
            lines.append(f"決定事項: {len(self.analysis.decisions)}件")
            lines.append(f"アクションアイテム: {len(self.analysis.action_items)}件")

        if self.document_url:
            lines.append(f"URL: {self.document_url}")

        return "\n".join(lines)
