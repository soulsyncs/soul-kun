"""
アナウンス機能ハンドラー

管理部またはカズさんからのアナウンス依頼を処理し、
指定チャットルームにオールメンション送信・タスク作成する機能。

分割元: 新規作成
作成日: 2026-01-25
バージョン: v10.26.0

機能:
- 自然言語でのアナウンス依頼解析
- 曖昧なルーム名のマッチング
- 確認フローでの安全な実行
- 即時/予約/繰り返し実行
- タスク一括作成（除外者指定可能）
- パターン検知連携（A1統合）
"""

import hashlib
import json
import re
import traceback
import sqlalchemy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any, List, Callable, Tuple
from uuid import UUID
import pytz

JST = pytz.timezone('Asia/Tokyo')


# =====================================================
# 定数
# =====================================================

class ScheduleType(str, Enum):
    """スケジュールタイプ"""
    IMMEDIATE = "immediate"
    ONE_TIME = "one_time"
    RECURRING = "recurring"


class AnnouncementStatus(str, Enum):
    """アナウンス状態"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SCHEDULED = "scheduled"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


# パターン検知の閾値
PATTERN_THRESHOLD = 3  # 3回以上で定期化提案

# ルームマッチングの閾値
ROOM_MATCH_AUTO_SELECT_THRESHOLD = 0.8
ROOM_MATCH_CANDIDATE_THRESHOLD = 0.3

# 認可されたルームID
AUTHORIZED_ROOM_IDS = {
    405315911,  # 管理部グループチャット
    # カズさん1on1のroom_idはmain.pyから取得
}

# 認可されたアカウントID
ADMIN_ACCOUNT_ID = "1728974"  # カズさん

# デフォルトorganization_id
DEFAULT_ORG_ID = "org_soulsyncs"


# =====================================================
# データクラス
# =====================================================

@dataclass
class ParsedAnnouncementRequest:
    """解析されたアナウンス依頼"""
    raw_message: str
    target_room_query: str = ""
    target_room_id: Optional[int] = None
    target_room_name: Optional[str] = None
    target_room_candidates: List[Dict] = field(default_factory=list)

    message_content: str = ""

    create_tasks: bool = False
    task_deadline: Optional[datetime] = None
    task_assign_all: bool = False
    task_include_names: List[str] = field(default_factory=list)
    task_exclude_names: List[str] = field(default_factory=list)
    task_include_account_ids: List[int] = field(default_factory=list)
    task_exclude_account_ids: List[int] = field(default_factory=list)

    schedule_type: ScheduleType = ScheduleType.IMMEDIATE
    scheduled_at: Optional[datetime] = None
    cron_expression: Optional[str] = None
    cron_description: Optional[str] = None
    skip_holidays: bool = True
    skip_weekends: bool = True

    confidence: float = 0.0
    parse_errors: List[str] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_questions: List[str] = field(default_factory=list)


# =====================================================
# メインハンドラークラス
# =====================================================

class AnnouncementHandler:
    """
    アナウンス機能を管理するハンドラークラス

    設計パターン:
    - 依存性注入（既存ハンドラーと同様）
    - Feature Flag（USE_ANNOUNCEMENT_FEATURE）
    - シングルトン初期化（_get_announcement_handler()）

    使用例:
        handler = _get_announcement_handler()
        result = handler.handle_announcement_request(
            params, room_id, account_id, sender_name, context
        )
    """

    def __init__(
        self,
        get_pool: Callable,
        get_secret: Callable,
        call_chatwork_api_with_retry: Callable,
        get_room_members: Callable,
        get_all_rooms: Callable,
        create_chatwork_task: Callable,
        send_chatwork_message: Callable,
        is_business_day: Callable = None,
        get_non_business_day_reason: Callable = None,
        authorized_room_ids: set = None,
        admin_account_id: str = None,
        organization_id: str = None,
        kazu_dm_room_id: int = None,
    ):
        """
        Args:
            get_pool: DB接続プールを取得する関数
            get_secret: Secret Managerから秘密情報を取得する関数
            call_chatwork_api_with_retry: ChatWork APIリトライ付き呼び出し関数
            get_room_members: ルームメンバー取得関数
            get_all_rooms: 全ルーム一覧取得関数
            create_chatwork_task: タスク作成関数（TaskHandler経由）
            send_chatwork_message: メッセージ送信関数
            is_business_day: 営業日判定関数（オプション）
            get_non_business_day_reason: 非営業日理由取得関数（オプション）
            authorized_room_ids: 認可ルームID（オプション）
            admin_account_id: 管理者アカウントID（オプション）
            organization_id: デフォルトorganization_id（オプション）
            kazu_dm_room_id: カズさんとのDMルームID（オプション）
        """
        self.get_pool = get_pool
        self.get_secret = get_secret
        self.call_chatwork_api_with_retry = call_chatwork_api_with_retry
        self.get_room_members = get_room_members
        self.get_all_rooms = get_all_rooms
        self.create_chatwork_task = create_chatwork_task
        self.send_chatwork_message = send_chatwork_message
        self.is_business_day = is_business_day
        self.get_non_business_day_reason = get_non_business_day_reason

        # 設定
        self._authorized_room_ids = authorized_room_ids or AUTHORIZED_ROOM_IDS
        self._admin_account_id = admin_account_id or ADMIN_ACCOUNT_ID
        self._organization_id = organization_id or DEFAULT_ORG_ID

        # カズさんDMルームがあれば追加
        if kazu_dm_room_id:
            self._authorized_room_ids = self._authorized_room_ids | {kazu_dm_room_id}

    # =========================================================================
    # 認可チェック
    # =========================================================================

    def is_authorized_request(
        self,
        room_id: str,
        account_id: str
    ) -> Tuple[bool, str]:
        """
        リクエストが認可されているかチェック

        Args:
            room_id: リクエスト元のルームID
            account_id: リクエスト者のアカウントID

        Returns:
            (is_authorized, reason)

        認可ルール:
        - カズさん（管理者）: どのルームからでも使用可能
        - 管理部メンバー: 管理部チャットからのみ使用可能（将来対応）
        """
        # カズさんはどこからでもOK（個人チャット、グループ、どこでも）
        if str(account_id) == self._admin_account_id:
            return True, ""

        # それ以外は認可ルームのみ
        room_id_int = int(room_id) if room_id else 0
        if room_id_int not in self._authorized_room_ids:
            return False, "この機能は管理部チャットからのみ使用できます"

        # TODO: 管理部ロールチェック（Phase 3.5連携）
        # 現時点では管理部チャットからでもカズさん以外は使用不可

        return False, "この機能は管理者のみが使用できます"

    # =========================================================================
    # メインエントリポイント
    # =========================================================================

    def handle_announcement_request(
        self,
        params: Dict[str, Any],
        room_id: str,
        account_id: str,
        sender_name: str,
        context: Dict[str, Any] = None
    ) -> str:
        """
        アナウンス依頼のメインエントリポイント

        状態マシン:
        1. 依頼解析 → ParsedAnnouncementRequest
        2. 不足情報があれば質問
        3. 確認メッセージ表示、DBに保存
        4. 確認応答で実行/スケジュール

        Args:
            params: AI司令塔からのパラメータ
            room_id: リクエスト元ルームID
            account_id: リクエスト者アカウントID
            sender_name: リクエスト者名
            context: 会話コンテキスト（フォローアップ用）

        Returns:
            ユーザーへの応答メッセージ
        """
        try:
            # 認可チェック
            authorized, reason = self.is_authorized_request(room_id, account_id)
            if not authorized:
                return f"🚫 {reason}"

            # フォローアップ応答かチェック（コンテキスト経由）
            if context and context.get("awaiting_announcement_response"):
                return self._handle_follow_up_response(
                    params, room_id, account_id, sender_name, context
                )

            # DBから pending announcement をチェック（リクエスト間でのコンテキスト保持）
            pending = self._get_pending_announcement(room_id, account_id)
            if pending:
                # pending announcement があればフォローアップとして処理
                context = {
                    "awaiting_announcement_response": True,
                    "pending_announcement_id": str(pending["id"]),
                }
                return self._handle_follow_up_response(
                    params, room_id, account_id, sender_name, context
                )

            # 依頼解析
            raw_message = params.get("raw_message", "")
            parsed = self._parse_announcement_request(raw_message, account_id)

            # 不足情報があれば質問
            if parsed.needs_clarification:
                return self._request_clarification(parsed, room_id, account_id)

            # ルーム解決
            if not parsed.target_room_id:
                parsed = self._resolve_room(parsed)

            # ルーム未確定なら候補提示
            if not parsed.target_room_id:
                return self._handle_room_candidates(parsed, room_id, account_id)

            # v10.26.1: MVVベースでメッセージをソウルくんらしく変換
            if parsed.message_content:
                enhanced_message = self._enhance_message_with_soulkun_style(
                    raw_intent=parsed.message_content,
                    target_room_name=parsed.target_room_name or "",
                    sender_name=sender_name
                )
                parsed.message_content = enhanced_message

            # 確認メッセージ生成・保存
            return self._generate_confirmation(parsed, room_id, account_id, sender_name)

        except Exception as e:
            print(f"❌ アナウンス処理エラー: {e}")
            traceback.print_exc()
            return "申し訳ありませんウル... アナウンス処理中にエラーが発生しましたウル。"

    # =========================================================================
    # 依頼解析
    # =========================================================================

    def _parse_announcement_request(
        self,
        message: str,
        requester_account_id: str
    ) -> ParsedAnnouncementRequest:
        """
        自然言語のアナウンス依頼を解析

        LLMを使用して構造化データに変換

        Args:
            message: ユーザーの依頼メッセージ
            requester_account_id: 依頼者のアカウントID

        Returns:
            ParsedAnnouncementRequest
        """
        try:
            api_key = self.get_secret("openrouter-api-key")

            system_prompt = self._get_parsing_system_prompt()

            import httpx
            response = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "google/gemini-3-flash-preview",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message}
                    ],
                    "max_tokens": 1000,
                    "temperature": 0.1,
                },
                timeout=20.0
            )

            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                # JSONを抽出
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    parsed_json = json.loads(json_match.group())
                    return self._json_to_parsed_request(parsed_json, message)

        except Exception as e:
            print(f"⚠️ アナウンス解析エラー: {e}")

        # フォールバック
        return ParsedAnnouncementRequest(
            raw_message=message,
            needs_clarification=True,
            clarification_questions=[
                "どのチャットルームに送りたいですか？",
                "何を伝えたいですか？"
            ]
        )

    def _get_parsing_system_prompt(self) -> str:
        """解析用システムプロンプトを取得"""
        return """あなたはアナウンス依頼を解析するアシスタントです。

ユーザーからのアナウンス依頼を分析し、以下の情報をJSON形式で抽出してください:

{
  "target_room_query": "送信先ルームの検索キーワード（ユーザーの言葉そのまま）",
  "message_content": "送信するメッセージ内容（ユーザーが指定した内容、または推測した内容）",
  "create_tasks": true/false,
  "task_deadline": "YYYY-MM-DD HH:MM",
  "task_assign_all": true/false,
  "task_include_names": ["名前1", "名前2"],
  "task_exclude_names": ["名前3"],
  "schedule_type": "immediate/one_time/recurring",
  "scheduled_at": "YYYY-MM-DD HH:MM",
  "cron_description": "毎週月曜9時",
  "skip_holidays": true/false,
  "skip_weekends": true/false,
  "confidence": 0.0-1.0,
  "needs_clarification": true/false,
  "clarification_questions": ["不明点1", "不明点2"]
}

【判断基準】
- 「連絡して」「伝えて」「お知らせして」→ アナウンス
- 「タスクも振って」「依頼して」「お願いして」→ create_tasks: true
- 「〜まで」「〜日まで」→ task_deadline
- 「全員」「みんな」→ task_assign_all: true
- 「〇〇にタスク」「〇〇さんにタスク」→ task_include_names: ["〇〇"], task_assign_all: false
- 「〜以外」「〜を除く」→ task_exclude_names, task_assign_all: true
- 「毎週」「毎月」「毎日」→ schedule_type: recurring
- 「明日」「来週月曜」→ schedule_type: one_time + scheduled_at

【重要ルール】
- 特定の人名が指定された場合（例:「麻美にタスク」）は必ず task_assign_all: false にして、task_include_names にその名前を入れる
- 「全員」「みんな」と明示的に言われた場合のみ task_assign_all: true にする
- 名前が指定されていない場合でも、デフォルトは task_assign_all: false にする

【必須確認項目】
メッセージ内容が明確でない場合はneeds_clarification: trueにしてください。
"""

    def _json_to_parsed_request(
        self,
        parsed_json: Dict,
        raw_message: str
    ) -> ParsedAnnouncementRequest:
        """JSONをParsedAnnouncementRequestに変換"""
        schedule_type_str = parsed_json.get("schedule_type", "immediate")
        try:
            schedule_type = ScheduleType(schedule_type_str)
        except ValueError:
            schedule_type = ScheduleType.IMMEDIATE

        # 日時パース
        scheduled_at = None
        if parsed_json.get("scheduled_at"):
            try:
                scheduled_at = datetime.strptime(
                    parsed_json["scheduled_at"],
                    "%Y-%m-%d %H:%M"
                ).replace(tzinfo=JST)
            except ValueError:
                pass

        task_deadline = None
        if parsed_json.get("task_deadline"):
            try:
                task_deadline = datetime.strptime(
                    parsed_json["task_deadline"],
                    "%Y-%m-%d %H:%M"
                ).replace(tzinfo=JST)
            except ValueError:
                pass

        return ParsedAnnouncementRequest(
            raw_message=raw_message,
            target_room_query=parsed_json.get("target_room_query", ""),
            message_content=parsed_json.get("message_content", ""),
            create_tasks=parsed_json.get("create_tasks", False),
            task_deadline=task_deadline,
            task_assign_all=parsed_json.get("task_assign_all", False),
            task_include_names=parsed_json.get("task_include_names", []),
            task_exclude_names=parsed_json.get("task_exclude_names", []),
            schedule_type=schedule_type,
            scheduled_at=scheduled_at,
            cron_description=parsed_json.get("cron_description"),
            skip_holidays=parsed_json.get("skip_holidays", True),
            skip_weekends=parsed_json.get("skip_weekends", True),
            confidence=parsed_json.get("confidence", 0.5),
            needs_clarification=parsed_json.get("needs_clarification", False),
            clarification_questions=parsed_json.get("clarification_questions", [])
        )

    # =========================================================================
    # v10.26.1: MVVベースメッセージ生成（ソウルくんらしい文章に変換）
    # =========================================================================

    def _enhance_message_with_soulkun_style(
        self,
        raw_intent: str,
        target_room_name: str = "",
        sender_name: str = ""
    ) -> str:
        """
        ユーザーの意図をソウルくんらしいメッセージに変換

        Phase 2C-1のMVV・アチーブ連携を活用し、
        雑な依頼でも意図を汲み取った優秀な秘書として文章を作成する。

        Args:
            raw_intent: ユーザーの伝えたい内容（「おはよう」等）
            target_room_name: 送信先ルーム名（コンテキスト用）
            sender_name: 依頼者の名前

        Returns:
            ソウルくんらしく変換されたメッセージ
        """
        try:
            api_key = self.get_secret("OPENROUTER_API_KEY")
            if not api_key:
                print("⚠️ OPENROUTER_API_KEY not found, using raw message")
                return raw_intent

            import httpx

            system_prompt = self._get_message_enhancement_prompt()
            user_prompt = f"""以下の内容を、ソウルくん（狼キャラクター）が送るアナウンスメッセージとして書き換えてください。

【伝えたい内容】
{raw_intent}

【送信先】
{target_room_name or "不明"}

【依頼者】
{sender_name or "管理者"}

【出力形式】
そのままアナウンスとして送信できる文章のみを出力してください。
説明や「以下がメッセージです」のような前置きは不要です。
"""

            response = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "google/gemini-3-flash-preview",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "max_tokens": 500,
                    "temperature": 0.7,  # 少し創造性を持たせる
                },
                timeout=15.0
            )

            if response.status_code == 200:
                enhanced = response.json()["choices"][0]["message"]["content"].strip()
                # コードブロックや引用符を除去
                enhanced = re.sub(r'^```\w*\n?', '', enhanced)
                enhanced = re.sub(r'\n?```$', '', enhanced)
                enhanced = enhanced.strip('"\'')
                print(f"✅ メッセージ変換完了: {raw_intent[:20]}... → {enhanced[:30]}...")
                return enhanced

        except Exception as e:
            print(f"⚠️ メッセージ変換エラー（元のメッセージを使用）: {e}")

        return raw_intent

    def _get_message_enhancement_prompt(self) -> str:
        """メッセージ変換用のシステムプロンプト"""
        return """あなたは「ソウルくん」という名前の、株式会社ソウルシンクスの公式キャラクターです。
狼をモチーフにした可愛らしいキャラクターで、語尾に「ウル」をつけて話します。

【ソウルシンクスのMVV】
- ミッション: 可能性の解放
- ビジョン: 心で繋がる未来を創る
- スローガン: 感謝で自分を満たし、満たした自分で相手を満たし、目の前のことに魂を込め、困っている人を助ける

【コミュニケーションスタイル】
- フレンドリーで親しみやすい
- 相手を応援し、可能性を信じる
- 前向きで明るいトーン
- 強制ではなく、提案や応援のスタンス
- メンバーの自主性を尊重

【アチーブメント流コミュニケーション】
- 選択理論: 「～しなければならない」→「～できたらいいね」
- 自己決定理論: 自律性・有能感・関係性を大切に
- サーバントリーダーシップ: 支える立場で接する

【変換ルール】
1. 語尾に「ウル」をつける（ただし自然な範囲で）
2. 命令口調は避け、お願いや提案の形にする
3. 相手を思いやる一言を添える
4. 必要に応じて絵文字を使う（🐺✨🎉など、最小限に）
5. 長すぎず、簡潔にまとめる

【禁止事項】
- 上から目線の表現
- プレッシャーを与える表現
- 機械的・事務的すぎる文章

【例】
入力: 「おはよう」
出力: おはようウル！🐺 今日も一日、みんなで頑張っていこうウル✨

入力: 「明日までに資料を提出してください」
出力: 明日までに資料の提出をお願いしたいウル！🐺 忙しいところ申し訳ないけど、よろしくお願いしますウル✨

入力: 「会議の時間が変更になりました」
出力: お知らせウル！🐺 会議の時間が変更になったウル。確認をお願いしますウル✨
"""

    # =========================================================================
    # ルーム解決（曖昧マッチング）
    # =========================================================================

    def _resolve_room(
        self,
        parsed: ParsedAnnouncementRequest
    ) -> ParsedAnnouncementRequest:
        """
        曖昧なルーム名を解決

        Args:
            parsed: 解析済みリクエスト

        Returns:
            ルーム情報が追加されたリクエスト
        """
        query = parsed.target_room_query
        if not query:
            return parsed

        room_id, room_name, candidates = self._fuzzy_match_room(query)

        parsed.target_room_id = room_id
        parsed.target_room_name = room_name
        parsed.target_room_candidates = candidates

        return parsed

    def _fuzzy_match_room(
        self,
        query: str
    ) -> Tuple[Optional[int], Optional[str], List[Dict]]:
        """
        ルーム名の曖昧マッチング

        Args:
            query: 検索クエリ（「合宿のチャット」等）

        Returns:
            (room_id, room_name, candidates)
        """
        all_rooms = self.get_all_rooms()
        if not all_rooms:
            return None, None, []

        query_normalized = self._normalize_for_matching(query)

        scored_rooms = []
        for room in all_rooms:
            room_name = room.get("name", "")
            room_id = room.get("room_id")
            room_type = room.get("type", "")

            # マイチャットはスキップ
            if room_type == "my":
                continue

            score = self._calculate_room_match_score(query_normalized, room_name)
            if score >= ROOM_MATCH_CANDIDATE_THRESHOLD:
                scored_rooms.append({
                    "room_id": room_id,
                    "room_name": room_name,
                    "score": score
                })

        # スコア降順でソート
        scored_rooms.sort(key=lambda x: x["score"], reverse=True)

        # 高スコアなら自動選択
        if scored_rooms and scored_rooms[0]["score"] >= ROOM_MATCH_AUTO_SELECT_THRESHOLD:
            top = scored_rooms[0]
            return top["room_id"], top["room_name"], []

        # 候補があれば返す
        if scored_rooms:
            return None, None, scored_rooms[:5]

        return None, None, []

    def _normalize_for_matching(self, text: str) -> str:
        """マッチング用に正規化"""
        # サフィックス除去（複合パターンを先に、長いものから順に）
        suffixes = [
            'のグループチャット',
            'グループチャット',
            'のチャット',
            'のグループ',
            'チャット',
            'グループ',
            'ルーム',
            'チーム',
        ]
        for suffix in suffixes:
            if text.endswith(suffix):
                text = text[:-len(suffix)]
                break

        # 特殊文字除去（【】★☆◆◇■□●○など）
        text = re.sub(r'[【】★☆◆◇■□●○「」『』〈〉《》]', '', text)

        # スペース正規化
        text = re.sub(r'\s+', '', text)
        # 小文字化
        return text.lower()

    def _calculate_room_match_score(self, query: str, room_name: str) -> float:
        """ルームマッチスコアを計算"""
        room_normalized = self._normalize_for_matching(room_name)

        # 完全一致
        if query == room_normalized:
            return 1.0

        # クエリがルーム名に含まれる
        if query in room_normalized:
            return 0.8 + (len(query) / len(room_normalized)) * 0.2

        # ルーム名がクエリに含まれる
        if room_normalized in query:
            return 0.7 + (len(room_normalized) / len(query)) * 0.1

        # 部分マッチ
        query_parts = re.split(r'[\s、・]', query)
        room_parts = re.split(r'[\s、・【】（）]', room_name)

        matches = 0
        for qp in query_parts:
            if qp and any(qp in rp.lower() or rp.lower() in qp for rp in room_parts):
                matches += 1

        if matches > 0 and query_parts:
            return 0.3 + (matches / len(query_parts)) * 0.4

        return 0.0

    # =========================================================================
    # v10.26.3: 名前からアカウントIDへの変換
    # =========================================================================

    def _resolve_names_to_account_ids(
        self,
        parsed: ParsedAnnouncementRequest
    ) -> ParsedAnnouncementRequest:
        """
        task_include_names の名前をアカウントIDに変換

        ルームメンバーから名前をマッチングし、
        task_include_account_ids に変換する。

        Args:
            parsed: 解析済みリクエスト（task_include_names を含む）

        Returns:
            アカウントIDが設定されたリクエスト
        """
        if not parsed.task_include_names or not parsed.target_room_id:
            return parsed

        # ルームメンバー取得
        members = self.get_room_members(str(parsed.target_room_id))
        if not members:
            print(f"⚠️ ルームメンバーが取得できませんでした: room_id={parsed.target_room_id}")
            return parsed

        # 名前→アカウントIDのマッピング
        resolved_ids = []
        unresolved_names = []

        for target_name in parsed.task_include_names:
            matched = self._match_name_to_member(target_name, members)
            if matched:
                resolved_ids.append(matched["account_id"])
                print(f"✅ 名前解決: {target_name} → {matched['account_id']} ({matched.get('name', '不明')})")
            else:
                unresolved_names.append(target_name)
                print(f"⚠️ 名前未解決: {target_name}")

        # 結果を設定
        if resolved_ids:
            parsed.task_include_account_ids = resolved_ids
            # 特定の人を指定した場合、task_assign_all は False
            parsed.task_assign_all = False

        return parsed

    def _match_name_to_member(
        self,
        target_name: str,
        members: List[Dict]
    ) -> Optional[Dict]:
        """
        名前をルームメンバーにマッチング

        マッチング優先度:
        1. 完全一致
        2. 名前に含まれる（「麻美」→「田中 麻美」）
        3. カタカナ・ひらがな変換後の部分一致

        Args:
            target_name: 検索する名前
            members: ルームメンバーリスト

        Returns:
            マッチしたメンバー or None
        """
        target_normalized = target_name.strip().lower()

        # 完全一致
        for m in members:
            name = m.get("name", "")
            if name.lower() == target_normalized:
                return m

        # 部分一致（名前に含まれる）
        for m in members:
            name = m.get("name", "")
            # 「麻美」が「田中 麻美」に含まれる
            if target_normalized in name.lower():
                return m
            # 「田中」が「田中 麻美」に含まれる
            if name.lower() in target_normalized:
                return m

        # スペース・敬称を除去して再マッチ
        target_clean = re.sub(r'[\s　さん様]', '', target_normalized)
        for m in members:
            name = m.get("name", "")
            name_clean = re.sub(r'[\s　さん様]', '', name.lower())
            if target_clean in name_clean or name_clean in target_clean:
                return m

        return None

    # =========================================================================
    # 確認フロー
    # =========================================================================

    def _request_clarification(
        self,
        parsed: ParsedAnnouncementRequest,
        room_id: str,
        account_id: str
    ) -> str:
        """不足情報の質問を生成"""
        questions = parsed.clarification_questions or ["詳細を教えてください"]

        lines = [
            "📢 アナウンス依頼を受け付けましたウル！",
            "",
            "確認させてほしいことがあるウル：",
        ]

        for i, q in enumerate(questions, 1):
            lines.append(f"  {i}. {q}")

        return "\n".join(lines)

    def _handle_room_candidates(
        self,
        parsed: ParsedAnnouncementRequest,
        room_id: str,
        account_id: str
    ) -> str:
        """ルーム候補を提示"""
        if not parsed.target_room_candidates:
            return (
                f"🤔 「{parsed.target_room_query}」というチャットが見つからなかったウル...\n\n"
                "正確なルーム名を教えてもらえるウル？"
            )

        lines = [
            f"🔍 「{parsed.target_room_query}」に該当しそうなルームが複数あるウル：",
            ""
        ]

        for i, candidate in enumerate(parsed.target_room_candidates, 1):
            lines.append(f"  {i}. {candidate['room_name']}")

        lines.append("")
        lines.append("どのルームに送りたいか、番号か名前で教えてウル！")

        return "\n".join(lines)

    def _generate_confirmation(
        self,
        parsed: ParsedAnnouncementRequest,
        room_id: str,
        account_id: str,
        sender_name: str
    ) -> str:
        """確認メッセージを生成"""

        # v10.26.3: 名前からアカウントIDに変換
        if parsed.task_include_names and parsed.target_room_id:
            parsed = self._resolve_names_to_account_ids(parsed)

        # DBに保存
        announcement_id = self._save_pending_announcement(
            parsed, room_id, account_id, sender_name
        )

        # 確認メッセージ組み立て
        lines = [
            "📢 **アナウンス確認**",
            "",
            f"**送信先**: {parsed.target_room_name}",
            "",
            "**メッセージ**:",
            "```",
            parsed.message_content,
            "```",
        ]

        # タスク作成セクション
        lines.append("")
        if parsed.create_tasks:
            lines.append("**タスク作成**: はい")
            if parsed.task_assign_all:
                lines.append("  - 対象: ルーム全員")
            elif parsed.task_include_names:
                lines.append(f"  - 対象: {', '.join(parsed.task_include_names)}")
            else:
                lines.append("  - 対象: ルーム全員")
            if parsed.task_exclude_names:
                lines.append(f"  - 除外: {', '.join(parsed.task_exclude_names)}")
            if parsed.task_deadline:
                lines.append(f"  - 期限: {parsed.task_deadline.strftime('%Y/%m/%d %H:%M')}")
            else:
                lines.append("  - 期限: なし")
        else:
            lines.append("**タスク作成**: なし")
            lines.append("  💡 タスクも作る場合は「タスクも作って」と追記してください")
            lines.append("  （例: 「全員にタスク、来週金曜まで」「田中さん以外にタスク」）")

        if parsed.schedule_type == ScheduleType.ONE_TIME:
            lines.append("")
            lines.append(f"**実行予定**: {parsed.scheduled_at.strftime('%Y/%m/%d %H:%M')}")
        elif parsed.schedule_type == ScheduleType.RECURRING:
            lines.append("")
            lines.append(f"**繰り返し**: {parsed.cron_description or parsed.cron_expression}")
            if parsed.skip_holidays:
                lines.append("  - 祝日はスキップ")
            if parsed.skip_weekends:
                lines.append("  - 土日はスキップ")

        lines.extend([
            "",
            "---",
            "「OK」または「送信」で実行します。",
            "「キャンセル」で取り消します。",
            "修正したい場合は具体的に教えてください。",
        ])

        return "\n".join(lines)

    # =========================================================================
    # フォローアップ応答処理
    # =========================================================================

    def _handle_follow_up_response(
        self,
        params: Dict[str, Any],
        room_id: str,
        account_id: str,
        sender_name: str,
        context: Dict[str, Any]
    ) -> Optional[str]:
        """確認応答やルーム選択の処理

        Returns:
            str: 応答メッセージ
            None: フォローアップではないと判断した場合（AI司令塔に委ねる）
        """
        response_text = params.get("raw_message", "").strip().lower()
        raw_message = params.get("raw_message", "")
        announcement_id = context.get("pending_announcement_id")

        # v10.26.5: 明らかにフォローアップではないメッセージはAI司令塔に委ねる
        # 質問パターン（「教えて」「確認して」「見せて」等）
        query_patterns = ["教えて", "確認して", "見せて", "調べて", "探して", "検索して", "一覧", "リスト"]
        # 自己参照パターン（「自分の」「私の」「俺の」「僕の」等）
        self_reference = ["自分の", "私の", "俺の", "僕の", "わたしの"]

        is_query = any(p in raw_message for p in query_patterns)
        is_self_ref = any(p in raw_message for p in self_reference)

        # 質問+自己参照は明らかに別のリクエスト（例: 「自分のタスク教えて」）
        if is_query and is_self_ref:
            print(f"📢 フォローアップではない（質問+自己参照）: {raw_message[:50]}")
            return None  # AI司令塔に委ねる

        # 質問パターンのみでも、アナウンス関連でなければスキップ
        if is_query and "アナウンス" not in raw_message and "送信" not in raw_message:
            print(f"📢 フォローアップではない（質問パターン）: {raw_message[:50]}")
            return None  # AI司令塔に委ねる

        # 確認応答
        if response_text in ["ok", "おっけー", "送信", "実行", "はい", "yes"]:
            if announcement_id:
                return self._execute_announcement_by_id(announcement_id)
            return "⚠️ 確認待ちのアナウンスが見つかりませんウル"

        # キャンセル
        if response_text in ["キャンセル", "やめる", "取り消し", "cancel", "no"]:
            if announcement_id:
                self._cancel_announcement(announcement_id, "ユーザーによるキャンセル")
            return "アナウンスをキャンセルしましたウル 📭"

        # ルーム番号選択
        if response_text.isdigit():
            candidates = context.get("room_candidates", [])
            idx = int(response_text) - 1
            if 0 <= idx < len(candidates):
                selected = candidates[idx]
                # 選択されたルームで再処理
                return self._retry_with_selected_room(
                    context, selected, room_id, account_id, sender_name
                )

        # タスク追加の指示
        raw_message = params.get("raw_message", "")
        task_keywords = ["タスク", "task"]
        if any(kw in raw_message for kw in task_keywords) and announcement_id:
            return self._update_task_settings(
                announcement_id, raw_message, room_id, account_id, sender_name
            )

        # v10.26.2: メッセージ内容の修正リクエスト
        # v10.26.4: 「〇〇って伝えて」「〇〇って言って」等の自然な表現を追加
        modification_keywords = [
            "追記", "追加", "変更", "修正", "書き換え", "直して", "変えて", "入れて",
            "伝えて", "言って", "にして", "メッセージ", "内容"
        ]
        if any(kw in raw_message for kw in modification_keywords) and announcement_id:
            return self._update_message_content(
                announcement_id, raw_message, room_id, account_id, sender_name
            )

        return "すみませんウル、応答を理解できませんでしたウル。「OK」か「キャンセル」、または修正内容を教えてウル！"

    def _update_task_settings(
        self,
        announcement_id: str,
        message: str,
        room_id: str,
        account_id: str,
        sender_name: str
    ) -> str:
        """タスク設定を更新し、確認メッセージを再表示"""
        pool = self.get_pool()

        try:
            with pool.connect() as conn:
                # 現在のアナウンス情報を取得
                result = conn.execute(
                    sqlalchemy.text("""
                        SELECT
                            id, message_content, target_room_id, target_room_name,
                            create_tasks, task_deadline, task_assign_all_members,
                            task_include_account_ids, task_exclude_account_ids,
                            schedule_type, scheduled_at, cron_expression,
                            cron_description, skip_holidays, skip_weekends
                        FROM scheduled_announcements
                        WHERE id = :id
                          AND organization_id = :org_id
                          AND status = 'pending'
                    """),
                    {"id": announcement_id, "org_id": self._organization_id}
                )
                row = result.mappings().fetchone()

                if not row:
                    return "⚠️ 確認待ちのアナウンスが見つかりませんウル"

                # タスク設定を解析
                create_tasks = True
                task_assign_all = True
                task_deadline = None
                task_exclude_account_ids = list(row["task_exclude_account_ids"] or [])
                task_include_account_ids = list(row["task_include_account_ids"] or [])

                # 「全員」「みんな」の検出
                if "全員" in message or "みんな" in message:
                    task_assign_all = True

                # 除外の検出: 「〇〇以外」
                exclude_match = re.search(r'([^\s、,]+)(?:さん)?以外', message)
                if exclude_match:
                    exclude_name = exclude_match.group(1)
                    # ここでは名前のみ記録（IDへの変換は実行時に行う）
                    # TODO: 名前→アカウントIDの変換

                # 期限の検出
                deadline_parsed = self._parse_deadline(message)
                if deadline_parsed:
                    task_deadline = deadline_parsed

                # DBを更新
                conn.execute(
                    sqlalchemy.text("""
                        UPDATE scheduled_announcements
                        SET create_tasks = :create_tasks,
                            task_assign_all_members = :task_assign_all,
                            task_deadline = :task_deadline,
                            updated_at = NOW()
                        WHERE id = :id
                          AND organization_id = :org_id
                    """),
                    {
                        "id": announcement_id,
                        "org_id": self._organization_id,
                        "create_tasks": create_tasks,
                        "task_assign_all": task_assign_all,
                        "task_deadline": task_deadline,
                    }
                )
                conn.commit()

                # 更新後の確認メッセージを生成
                lines = [
                    "📢 **アナウンス確認（タスク追加）**",
                    "",
                    f"**送信先**: {row['target_room_name']}",
                    "",
                    "**メッセージ**:",
                    "```",
                    row["message_content"],
                    "```",
                    "",
                    "**タスク作成**: はい ✅",
                    f"  - 対象: {'ルーム全員' if task_assign_all else '指定メンバー'}",
                ]

                if task_deadline:
                    lines.append(f"  - 期限: {task_deadline.strftime('%Y/%m/%d %H:%M')}")
                else:
                    lines.append("  - 期限: なし（期限を指定する場合は「来週金曜まで」等と追記してください）")

                lines.extend([
                    "",
                    "---",
                    "「OK」または「送信」で実行します。",
                    "「キャンセル」で取り消します。",
                ])

                return "\n".join(lines)

        except Exception as e:
            print(f"[AnnouncementHandler] タスク設定更新エラー: {e}")
            return "⚠️ タスク設定の更新中にエラーが発生しましたウル"

    def _update_message_content(
        self,
        announcement_id: str,
        modification_request: str,
        room_id: str,
        account_id: str,
        sender_name: str
    ) -> str:
        """
        v10.26.2: メッセージ内容を修正

        ユーザーの修正リクエストをLLMで解釈し、元のメッセージを更新する。

        Args:
            announcement_id: アナウンスID
            modification_request: ユーザーの修正依頼（例: "これはテストだよっていうのを追記して"）
            room_id: リクエスト元ルームID
            account_id: リクエスト者アカウントID
            sender_name: リクエスト者名

        Returns:
            更新後の確認メッセージ
        """
        pool = self.get_pool()

        try:
            with pool.connect() as conn:
                # 現在のアナウンス情報を取得
                result = conn.execute(
                    sqlalchemy.text("""
                        SELECT
                            id, message_content, target_room_id, target_room_name,
                            create_tasks, task_deadline, task_assign_all_members,
                            task_include_account_ids, task_exclude_account_ids,
                            schedule_type, scheduled_at, cron_expression,
                            cron_description, skip_holidays, skip_weekends
                        FROM scheduled_announcements
                        WHERE id = :id
                          AND organization_id = :org_id
                          AND status = 'pending'
                    """),
                    {"id": announcement_id, "org_id": self._organization_id}
                )
                row = result.mappings().fetchone()

                if not row:
                    return "⚠️ 確認待ちのアナウンスが見つかりませんウル"

                current_message = row["message_content"]

                # LLMでメッセージを修正
                updated_message = self._apply_message_modification(
                    current_message, modification_request, sender_name
                )

                # DBを更新
                conn.execute(
                    sqlalchemy.text("""
                        UPDATE scheduled_announcements
                        SET message_content = :message_content,
                            updated_at = NOW()
                        WHERE id = :id
                          AND organization_id = :org_id
                    """),
                    {
                        "id": announcement_id,
                        "org_id": self._organization_id,
                        "message_content": updated_message,
                    }
                )
                conn.commit()

                print(f"✅ メッセージ修正: {current_message[:30]}... → {updated_message[:30]}...")

                # 更新後の確認メッセージを生成
                lines = [
                    "📢 **アナウンス確認（メッセージ修正済み）**",
                    "",
                    f"**送信先**: {row['target_room_name']}",
                    "",
                    "**メッセージ**:",
                    "```",
                    updated_message,
                    "```",
                ]

                # タスク情報
                lines.append("")
                if row["create_tasks"]:
                    lines.append("**タスク作成**: はい")
                    if row["task_assign_all_members"]:
                        lines.append("  - 対象: ルーム全員")
                    if row["task_deadline"]:
                        deadline = row["task_deadline"]
                        if hasattr(deadline, 'strftime'):
                            lines.append(f"  - 期限: {deadline.strftime('%Y/%m/%d %H:%M')}")
                        else:
                            lines.append(f"  - 期限: {deadline}")
                else:
                    lines.append("**タスク作成**: なし")

                lines.extend([
                    "",
                    "---",
                    "「OK」または「送信」で実行します。",
                    "「キャンセル」で取り消します。",
                    "さらに修正したい場合は具体的に教えてください。",
                ])

                return "\n".join(lines)

        except Exception as e:
            print(f"[AnnouncementHandler] メッセージ修正エラー: {e}")
            return "⚠️ メッセージの修正中にエラーが発生しましたウル"

    def _apply_message_modification(
        self,
        current_message: str,
        modification_request: str,
        sender_name: str
    ) -> str:
        """
        LLMを使ってメッセージを修正

        Args:
            current_message: 現在のメッセージ
            modification_request: ユーザーの修正依頼
            sender_name: 依頼者名

        Returns:
            修正されたメッセージ
        """
        # まずLLMで修正を試みる
        llm_result = self._try_llm_modification(current_message, modification_request)
        if llm_result:
            return llm_result

        # フォールバック: 単純に追記
        return self._fallback_modification(current_message, modification_request)

    def _try_llm_modification(
        self,
        current_message: str,
        modification_request: str
    ) -> Optional[str]:
        """LLMでメッセージ修正を試みる"""
        try:
            api_key = self.get_secret("OPENROUTER_API_KEY")
            if not api_key:
                print("⚠️ OPENROUTER_API_KEY not found, using fallback")
                return None

            import httpx

            system_prompt = """あなたはメッセージ編集アシスタントです。
ユーザーの修正依頼に基づいて、元のメッセージを適切に修正してください。

ルール:
1. 修正依頼を正確に反映する
2. 「追記」「追加」→ 元のメッセージに追加
3. 「変更」「修正」「書き換え」→ 該当部分を変更
4. ソウルくんの語尾「ウル」や絵文字のスタイルは維持する
5. 出力は修正後のメッセージのみ（説明不要）
"""

            user_prompt = f"""【元のメッセージ】
{current_message}

【修正依頼】
{modification_request}

修正後のメッセージを出力してください。"""

            response = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "google/gemini-3-flash-preview",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "max_tokens": 500,
                    "temperature": 0.3,  # 正確性重視
                },
                timeout=15.0
            )

            if response.status_code == 200:
                modified = response.json()["choices"][0]["message"]["content"].strip()
                # コードブロックや引用符を除去
                modified = re.sub(r'^```\w*\n?', '', modified)
                modified = re.sub(r'\n?```$', '', modified)
                modified = modified.strip('"\'')
                return modified

        except Exception as e:
            print(f"⚠️ メッセージ修正LLMエラー: {e}")

        return None

    def _fallback_modification(
        self,
        current_message: str,
        modification_request: str
    ) -> str:
        """フォールバック: 単純な追記処理"""
        if "追記" in modification_request or "追加" in modification_request or "入れて" in modification_request:
            # 追記内容を抽出する簡易ロジック
            # 「〇〇を追記して」「〇〇って追加して」等から内容を抽出
            patterns = [
                r'「([^」]+)」.*(?:追記|追加|入れて)',
                r'「([^」]+)」っていうの.*(?:追記|追加|入れて)',
                r'(.+?)(?:を|って|と)(?:追記|追加)',
            ]
            for pattern in patterns:
                match = re.search(pattern, modification_request)
                if match:
                    addition = match.group(1).strip()
                    if addition:
                        return f"{current_message}\n\n{addition}"

        return current_message

    def _parse_deadline(self, message: str) -> Optional[datetime]:
        """メッセージから期限を解析"""
        now = datetime.now(JST)

        # 「来週金曜」「来週の金曜日」
        weekday_map = {
            "月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6,
            "月曜": 0, "火曜": 1, "水曜": 2, "木曜": 3, "金曜": 4, "土曜": 5, "日曜": 6,
        }

        # 来週のパターン
        next_week_match = re.search(r'来週の?([月火水木金土日])(曜日?)?', message)
        if next_week_match:
            target_weekday = weekday_map.get(next_week_match.group(1), 4)  # デフォルト金曜
            days_ahead = target_weekday - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            days_ahead += 7  # 来週なので+7
            deadline = now + timedelta(days=days_ahead)
            return deadline.replace(hour=18, minute=0, second=0, microsecond=0)

        # 今週のパターン
        this_week_match = re.search(r'今週の?([月火水木金土日])(曜日?)?', message)
        if this_week_match:
            target_weekday = weekday_map.get(this_week_match.group(1), 4)
            days_ahead = target_weekday - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            deadline = now + timedelta(days=days_ahead)
            return deadline.replace(hour=18, minute=0, second=0, microsecond=0)

        # 「明日」
        if "明日" in message:
            deadline = now + timedelta(days=1)
            return deadline.replace(hour=18, minute=0, second=0, microsecond=0)

        # 「明後日」
        if "明後日" in message:
            deadline = now + timedelta(days=2)
            return deadline.replace(hour=18, minute=0, second=0, microsecond=0)

        # 「〇日後」
        days_later_match = re.search(r'(\d+)日後', message)
        if days_later_match:
            days = int(days_later_match.group(1))
            deadline = now + timedelta(days=days)
            return deadline.replace(hour=18, minute=0, second=0, microsecond=0)

        # 「〇/〇」「〇月〇日」形式
        date_match = re.search(r'(\d{1,2})[/月](\d{1,2})日?', message)
        if date_match:
            month = int(date_match.group(1))
            day = int(date_match.group(2))
            year = now.year
            if month < now.month:
                year += 1
            try:
                deadline = datetime(year, month, day, 18, 0, 0, tzinfo=JST)
                return deadline
            except ValueError:
                pass

        return None

    # =========================================================================
    # DB操作
    # =========================================================================

    def _get_pending_announcement(
        self,
        room_id: str,
        account_id: str
    ) -> Optional[Dict[str, Any]]:
        """このユーザー/ルームのpending announcementを取得"""
        pool = self.get_pool()

        try:
            with pool.connect() as conn:
                result = conn.execute(
                    sqlalchemy.text("""
                        SELECT id, message_content, target_room_id, target_room_name,
                               create_tasks, task_deadline, task_assign_all_members,
                               created_at
                        FROM scheduled_announcements
                        WHERE organization_id = :org_id
                          AND requested_by_account_id = :account_id
                          AND requested_from_room_id = :room_id
                          AND status = 'pending'
                          AND created_at > NOW() - INTERVAL '30 minutes'
                        ORDER BY created_at DESC
                        LIMIT 1
                    """),
                    {
                        "org_id": self._organization_id,
                        "account_id": int(account_id),
                        "room_id": int(room_id),
                    }
                )
                row = result.mappings().fetchone()
                if row:
                    return dict(row)
                return None
        except Exception as e:
            print(f"[AnnouncementHandler] pending取得エラー: {e}")
            return None

    def _save_pending_announcement(
        self,
        parsed: ParsedAnnouncementRequest,
        room_id: str,
        account_id: str,
        sender_name: str
    ) -> Optional[str]:
        """アナウンスをDBに保存"""
        pool = self.get_pool()

        try:
            with pool.connect() as conn:
                result = conn.execute(
                    sqlalchemy.text("""
                        INSERT INTO scheduled_announcements (
                            organization_id,
                            title,
                            message_content,
                            target_room_id,
                            target_room_name,
                            create_tasks,
                            task_deadline,
                            task_include_account_ids,
                            task_exclude_account_ids,
                            task_assign_all_members,
                            schedule_type,
                            scheduled_at,
                            cron_expression,
                            cron_description,
                            skip_holidays,
                            skip_weekends,
                            status,
                            requested_by_account_id,
                            requested_from_room_id
                        ) VALUES (
                            :org_id,
                            :title,
                            :message_content,
                            :target_room_id,
                            :target_room_name,
                            :create_tasks,
                            :task_deadline,
                            :task_include_account_ids,
                            :task_exclude_account_ids,
                            :task_assign_all_members,
                            :schedule_type,
                            :scheduled_at,
                            :cron_expression,
                            :cron_description,
                            :skip_holidays,
                            :skip_weekends,
                            'pending',
                            :requested_by_account_id,
                            :requested_from_room_id
                        )
                        RETURNING id
                    """),
                    {
                        "org_id": self._organization_id,
                        "title": parsed.message_content[:200] if parsed.message_content else "アナウンス",
                        "message_content": parsed.message_content,
                        "target_room_id": parsed.target_room_id,
                        "target_room_name": parsed.target_room_name,
                        "create_tasks": parsed.create_tasks,
                        "task_deadline": parsed.task_deadline,
                        "task_include_account_ids": parsed.task_include_account_ids or [],
                        "task_exclude_account_ids": parsed.task_exclude_account_ids or [],
                        "task_assign_all_members": parsed.task_assign_all,
                        "schedule_type": parsed.schedule_type.value,
                        "scheduled_at": parsed.scheduled_at,
                        "cron_expression": parsed.cron_expression,
                        "cron_description": parsed.cron_description,
                        "skip_holidays": parsed.skip_holidays,
                        "skip_weekends": parsed.skip_weekends,
                        "requested_by_account_id": int(account_id),
                        "requested_from_room_id": int(room_id),
                    }
                )
                conn.commit()
                row = result.fetchone()
                if row:
                    announcement_id = str(row[0])
                    print(f"✅ アナウンス保存: id={announcement_id}")

                    # パターン記録（A1連携）
                    self._record_announcement_pattern(parsed, account_id, conn)

                    return announcement_id

        except Exception as e:
            print(f"❌ アナウンス保存エラー: {e}")
            traceback.print_exc()

        return None

    def _cancel_announcement(
        self,
        announcement_id: str,
        reason: str
    ):
        """アナウンスをキャンセル"""
        pool = self.get_pool()
        try:
            with pool.connect() as conn:
                conn.execute(
                    sqlalchemy.text("""
                        UPDATE scheduled_announcements
                        SET status = 'cancelled',
                            cancelled_at = CURRENT_TIMESTAMP,
                            cancelled_reason = :reason
                        WHERE id = :id
                          AND organization_id = :org_id
                    """),
                    {"id": announcement_id, "reason": reason, "org_id": self._organization_id}
                )
                conn.commit()
                print(f"📭 アナウンスキャンセル: id={announcement_id}")
        except Exception as e:
            print(f"❌ キャンセルエラー: {e}")

    # =========================================================================
    # 実行
    # =========================================================================

    def _execute_announcement_by_id(self, announcement_id: str) -> str:
        """IDからアナウンスを実行"""
        result = self.execute_announcement(announcement_id)

        if result.get("success"):
            if result.get("skipped"):
                return f"📅 本日は{result.get('reason')}のため、スキップしましたウル"

            message = "📢 送信完了ウル！🎉"

            if result.get("tasks_created", 0) > 0:
                message += f"\n✅ {result['tasks_created']}人にタスクを作成しましたウル"

            return message
        else:
            errors = result.get("errors", ["不明なエラー"])
            return f"😢 送信に失敗しましたウル... ({errors[0]})"

    def execute_announcement(
        self,
        announcement_id: str,
        execution_context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        アナウンスを実行

        Args:
            announcement_id: アナウンスID
            execution_context: 実行コンテキスト（オプション）

        Returns:
            {
                "success": bool,
                "message_id": str,
                "tasks_created": int,
                "errors": [],
                "skipped": bool,
                "reason": str
            }
        """
        pool = self.get_pool()

        try:
            with pool.connect() as conn:
                # アナウンス取得（10の鉄則 #1: organization_idフィルタ必須）
                result = conn.execute(
                    sqlalchemy.text("""
                        SELECT * FROM scheduled_announcements
                        WHERE id = :id
                          AND organization_id = :org_id
                    """),
                    {"id": announcement_id, "org_id": self._organization_id}
                )
                row = result.fetchone()

                if not row:
                    return {"success": False, "errors": ["アナウンスが見つかりません"]}

                # RowをDictに変換
                columns = result.keys()
                announcement = dict(zip(columns, row))

                # 営業日チェック
                if self.is_business_day:
                    skip_weekends = announcement.get("skip_weekends", True)
                    skip_holidays = announcement.get("skip_holidays", True)

                    if skip_weekends or skip_holidays:
                        if not self.is_business_day():
                            reason = self.get_non_business_day_reason() if self.get_non_business_day_reason else "非営業日"
                            # 繰り返しなら次回計算
                            if announcement.get("schedule_type") == "recurring":
                                self._calculate_next_execution(announcement_id, conn)
                            return {"success": True, "skipped": True, "reason": reason}

                # ステータス更新（10の鉄則 #1: organization_idフィルタ必須）
                conn.execute(
                    sqlalchemy.text("""
                        UPDATE scheduled_announcements
                        SET status = 'executing'
                        WHERE id = :id
                          AND organization_id = :org_id
                    """),
                    {"id": announcement_id, "org_id": self._organization_id}
                )

                # ルームメンバー取得
                room_id = announcement["target_room_id"]
                members = self.get_room_members(str(room_id))
                members_snapshot = {m["account_id"]: m.get("name", "") for m in members}

                # 実行ログ作成
                log_id = self._create_execution_log(
                    announcement_id, members_snapshot, conn
                )

                # メッセージ送信
                # v10.26.1: return_details=True でmessage_idを取得
                message_with_toall = f"[toall]\n{announcement['message_content']}"
                message_result = self.send_chatwork_message(
                    str(room_id), message_with_toall, return_details=True
                )

                # v10.26.1: boolとdictの両方をサポート（後方互換性）
                if isinstance(message_result, dict):
                    message_id = message_result.get("message_id")
                    send_success = message_result.get("success", False)
                else:
                    # 旧実装（boolを返す場合）
                    message_id = None
                    send_success = bool(message_result)

                if not send_success:
                    raise Exception("メッセージ送信に失敗しました")

                # タスク作成
                tasks_created = 0
                task_errors = []

                if announcement.get("create_tasks"):
                    task_results = self._create_announcement_tasks(
                        announcement, members, conn
                    )
                    tasks_created = task_results["created"]
                    task_errors = task_results.get("errors", [])

                # ログ更新
                status = "completed" if not task_errors else "partial_failure"
                self._update_execution_log(
                    log_id,
                    message_sent=True,
                    message_id=message_id,
                    tasks_created=tasks_created,
                    status=status,
                    conn=conn
                )

                # アナウンスステータス更新
                final_status = "completed"
                if announcement.get("schedule_type") == "recurring":
                    final_status = "scheduled"
                    self._calculate_next_execution(announcement_id, conn)

                conn.execute(
                    sqlalchemy.text("""
                        UPDATE scheduled_announcements
                        SET status = :status,
                            last_executed_at = CURRENT_TIMESTAMP,
                            execution_count = execution_count + 1
                        WHERE id = :id
                          AND organization_id = :org_id
                    """),
                    {"id": announcement_id, "status": final_status, "org_id": self._organization_id}
                )
                conn.commit()

                return {
                    "success": True,
                    "message_id": message_id,
                    "tasks_created": tasks_created,
                    "errors": task_errors
                }

        except Exception as e:
            print(f"❌ アナウンス実行エラー: {e}")
            traceback.print_exc()
            # 10の鉄則 #8: エラーメッセージに機密情報を含めない
            return {"success": False, "errors": ["アナウンスの実行中にエラーが発生しました"]}

    def _create_announcement_tasks(
        self,
        announcement: Dict,
        members: List[Dict],
        conn
    ) -> Dict[str, Any]:
        """タスクを一括作成"""
        recipients = []

        task_assign_all = announcement.get("task_assign_all_members", False)
        include_ids = set(announcement.get("task_include_account_ids") or [])
        exclude_ids = set(announcement.get("task_exclude_account_ids") or [])

        for m in members:
            account_id = m.get("account_id")
            if not account_id:
                continue

            # 全員対象の場合
            if task_assign_all:
                if account_id not in exclude_ids:
                    recipients.append(m)
            # 指定者のみ
            elif include_ids:
                if account_id in include_ids:
                    recipients.append(m)

        # タスク作成
        created = 0
        errors = []
        task_ids = []

        room_id = str(announcement["target_room_id"])
        task_body = announcement["message_content"]
        task_deadline = announcement.get("task_deadline")
        limit_timestamp = int(task_deadline.timestamp()) if task_deadline else None

        for recipient in recipients:
            try:
                result = self.create_chatwork_task(
                    room_id=room_id,
                    task_body=task_body,
                    assigned_to_account_id=str(recipient["account_id"]),
                    limit=limit_timestamp
                )
                if result and result.get("task_ids"):
                    task_ids.extend(result["task_ids"])
                    created += 1
            except Exception as e:
                errors.append({
                    "account_id": recipient.get("account_id"),
                    "name": recipient.get("name"),
                    "error": str(e)
                })

        return {
            "created": created,
            "task_ids": task_ids,
            "errors": errors
        }

    # =========================================================================
    # ログ操作
    # =========================================================================

    def _create_execution_log(
        self,
        announcement_id: str,
        members_snapshot: Dict,
        conn
    ) -> Optional[str]:
        """実行ログを作成"""
        try:
            result = conn.execute(
                sqlalchemy.text("""
                    INSERT INTO announcement_logs (
                        organization_id,
                        announcement_id,
                        room_members_snapshot,
                        members_count,
                        status
                    ) VALUES (
                        :org_id,
                        :announcement_id,
                        :snapshot,
                        :count,
                        'in_progress'
                    )
                    RETURNING id
                """),
                {
                    "org_id": self._organization_id,
                    "announcement_id": announcement_id,
                    "snapshot": json.dumps(members_snapshot),
                    "count": len(members_snapshot),
                }
            )
            row = result.fetchone()
            return str(row[0]) if row else None
        except Exception as e:
            print(f"⚠️ ログ作成エラー: {e}")
            return None

    def _update_execution_log(
        self,
        log_id: str,
        message_sent: bool,
        message_id: str,
        tasks_created: int,
        status: str,
        conn
    ):
        """実行ログを更新（10の鉄則 #1: organization_idフィルタ必須）"""
        try:
            conn.execute(
                sqlalchemy.text("""
                    UPDATE announcement_logs
                    SET message_sent = :message_sent,
                        message_id = :message_id,
                        message_sent_at = CASE WHEN :message_sent THEN CURRENT_TIMESTAMP ELSE NULL END,
                        tasks_created = :tasks_created_flag,
                        task_count = :task_count,
                        status = :status
                    WHERE id = :id
                      AND organization_id = :org_id
                """),
                {
                    "id": log_id,
                    "message_sent": message_sent,
                    "message_id": message_id,
                    "tasks_created_flag": tasks_created > 0,
                    "task_count": tasks_created,
                    "status": status,
                    "org_id": self._organization_id,
                }
            )
        except Exception as e:
            print(f"⚠️ ログ更新エラー: {e}")

    def _calculate_next_execution(self, announcement_id: str, conn):
        """次回実行日時を計算（繰り返し用）（10の鉄則 #1: organization_idフィルタ必須）"""
        # TODO: croniter使用した計算
        # 現時点では単純に7日後を設定
        try:
            conn.execute(
                sqlalchemy.text("""
                    UPDATE scheduled_announcements
                    SET next_execution_at = CURRENT_TIMESTAMP + INTERVAL '7 days'
                    WHERE id = :id
                      AND organization_id = :org_id
                """),
                {"id": announcement_id, "org_id": self._organization_id}
            )
        except Exception as e:
            print(f"⚠️ 次回実行計算エラー: {e}")

    # =========================================================================
    # パターン検知（A1連携）
    # =========================================================================

    def _record_announcement_pattern(
        self,
        parsed: ParsedAnnouncementRequest,
        account_id: str,
        conn
    ):
        """アナウンス依頼パターンを記録"""
        try:
            # 正規化してハッシュ生成
            normalized = self._normalize_request_for_pattern(parsed)
            pattern_hash = hashlib.sha256(normalized.encode()).hexdigest()[:64]

            # Upsert
            result = conn.execute(
                sqlalchemy.text("""
                    INSERT INTO announcement_patterns (
                        organization_id,
                        pattern_hash,
                        normalized_request,
                        target_room_id,
                        target_room_name,
                        occurrence_count,
                        occurrence_timestamps,
                        last_occurred_at,
                        first_occurred_at,
                        requested_by_account_ids,
                        sample_requests
                    ) VALUES (
                        :org_id,
                        :hash,
                        :normalized,
                        :room_id,
                        :room_name,
                        1,
                        ARRAY[CURRENT_TIMESTAMP],
                        CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP,
                        ARRAY[:account_id::bigint],
                        ARRAY[:sample]
                    )
                    ON CONFLICT (organization_id, pattern_hash) DO UPDATE SET
                        occurrence_count = announcement_patterns.occurrence_count + 1,
                        occurrence_timestamps = array_append(
                            announcement_patterns.occurrence_timestamps,
                            CURRENT_TIMESTAMP
                        ),
                        last_occurred_at = CURRENT_TIMESTAMP,
                        requested_by_account_ids = CASE
                            WHEN :account_id::bigint = ANY(announcement_patterns.requested_by_account_ids)
                            THEN announcement_patterns.requested_by_account_ids
                            ELSE array_append(
                                announcement_patterns.requested_by_account_ids,
                                :account_id::bigint
                            )
                        END,
                        sample_requests = CASE
                            WHEN array_length(announcement_patterns.sample_requests, 1) >= 5
                            THEN announcement_patterns.sample_requests
                            ELSE array_append(
                                announcement_patterns.sample_requests,
                                :sample
                            )
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING occurrence_count, suggestion_created
                """),
                {
                    "org_id": self._organization_id,
                    "hash": pattern_hash,
                    "normalized": normalized,
                    "room_id": parsed.target_room_id,
                    "room_name": parsed.target_room_name,
                    "account_id": int(account_id),
                    "sample": parsed.raw_message[:500]
                }
            )

            row = result.fetchone()
            if row:
                count = row[0]
                suggestion_created = row[1]

                # 閾値超えかつ未提案なら提案作成
                if count >= PATTERN_THRESHOLD and not suggestion_created:
                    self._create_recurring_suggestion(pattern_hash, conn)

        except Exception as e:
            print(f"⚠️ パターン記録エラー: {e}")

    def _normalize_request_for_pattern(
        self,
        parsed: ParsedAnnouncementRequest
    ) -> str:
        """パターン検知用にリクエストを正規化"""
        # ルーム名 + メッセージ概要でハッシュ
        parts = []
        if parsed.target_room_name:
            parts.append(parsed.target_room_name)
        if parsed.message_content:
            # 最初の100文字
            parts.append(parsed.message_content[:100])
        return "|".join(parts).lower()

    def _create_recurring_suggestion(self, pattern_hash: str, conn):
        """定期化提案のインサイトを作成"""
        try:
            # パターン詳細取得
            result = conn.execute(
                sqlalchemy.text("""
                    SELECT * FROM announcement_patterns
                    WHERE organization_id = :org_id AND pattern_hash = :hash
                """),
                {"org_id": self._organization_id, "hash": pattern_hash}
            )
            pattern_row = result.fetchone()

            if not pattern_row:
                return

            columns = result.keys()
            pattern = dict(zip(columns, pattern_row))

            # インサイト作成
            title = f"「{pattern.get('target_room_name', '不明')}」へのアナウンスが繰り返されています"
            description = (
                f"過去{pattern['occurrence_count']}回、同様のアナウンスが依頼されました。\n"
                "定期実行に設定することを検討してください。"
            )

            insight_result = conn.execute(
                sqlalchemy.text("""
                    INSERT INTO soulkun_insights (
                        organization_id,
                        insight_type,
                        source_type,
                        source_id,
                        importance,
                        title,
                        description,
                        recommended_action,
                        evidence,
                        status,
                        classification
                    ) VALUES (
                        :org_id,
                        'pattern_detected',
                        'announcement_pattern',
                        :pattern_id,
                        'medium',
                        :title,
                        :description,
                        :action,
                        :evidence,
                        'new',
                        'internal'
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING id
                """),
                {
                    "org_id": self._organization_id,
                    "pattern_id": str(pattern["id"]),
                    "title": title[:200],
                    "description": description,
                    "action": "1. アナウンスを定期実行に変更\n2. 担当者に定期タスク化を提案",
                    "evidence": json.dumps({
                        "occurrence_count": pattern["occurrence_count"],
                        "target_room": pattern.get("target_room_name"),
                        "sample_requests": pattern.get("sample_requests", [])[:3]
                    })
                }
            )

            insight_row = insight_result.fetchone()
            if insight_row:
                # パターンを更新（10の鉄則 #1: organization_idフィルタ必須）
                conn.execute(
                    sqlalchemy.text("""
                        UPDATE announcement_patterns
                        SET suggestion_created = TRUE,
                            insight_id = :insight_id
                        WHERE id = :pattern_id
                          AND organization_id = :org_id
                    """),
                    {
                        "insight_id": str(insight_row[0]),
                        "pattern_id": str(pattern["id"]),
                        "org_id": self._organization_id
                    }
                )
                print(f"💡 定期化提案インサイト作成: {title}")

        except Exception as e:
            print(f"⚠️ 提案作成エラー: {e}")

    def _retry_with_selected_room(
        self,
        context: Dict,
        selected_room: Dict,
        room_id: str,
        account_id: str,
        sender_name: str
    ) -> str:
        """選択されたルームで再処理"""
        # コンテキストから元のパース結果を取得
        original_parsed = context.get("original_parsed")
        if not original_parsed:
            return "⚠️ 元の依頼情報が見つかりませんウル"

        # ルーム情報を設定
        original_parsed["target_room_id"] = selected_room["room_id"]
        original_parsed["target_room_name"] = selected_room["room_name"]

        # ParsedAnnouncementRequestに変換
        parsed = ParsedAnnouncementRequest(**original_parsed)

        # 確認メッセージ生成
        return self._generate_confirmation(parsed, room_id, account_id, sender_name)
