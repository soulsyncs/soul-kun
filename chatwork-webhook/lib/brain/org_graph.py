# lib/brain/org_graph.py
"""
ソウルくんの脳 - 組織グラフ理解（Organization Graph）

Ultimate Brain Phase 3: 人間関係、力学、信頼関係を理解するシステム

設計思想:
- 組織内の人物をノードとしてモデル化
- 人物間の関係をエッジとしてモデル化
- 影響力、専門性、コミュニケーションスタイルを属性として保持
- 会話や行動から関係性を自動学習

主要機能:
1. 人物の属性管理（影響力、専門性、スタイル）
2. 関係性の管理（上司-部下、メンター、協力者、対立）
3. 関係性の強度と信頼度の追跡
4. インタラクションからの自動学習
5. 組織構造の可視化

設計書: docs/19_ultimate_brain_architecture.md セクション5.2
"""

from __future__ import annotations

import asyncio
import logging
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

logger = logging.getLogger(__name__)


# =============================================================================
# 定数
# =============================================================================

# 影響力スコアの範囲
INFLUENCE_SCORE_MIN: float = 0.0
INFLUENCE_SCORE_MAX: float = 1.0
INFLUENCE_SCORE_DEFAULT: float = 0.5

# 信頼度スコアの範囲
TRUST_LEVEL_MIN: float = 0.0
TRUST_LEVEL_MAX: float = 1.0
TRUST_LEVEL_DEFAULT: float = 0.5

# 関係強度の範囲
RELATIONSHIP_STRENGTH_MIN: float = 0.0
RELATIONSHIP_STRENGTH_MAX: float = 1.0
RELATIONSHIP_STRENGTH_DEFAULT: float = 0.3

# インタラクション履歴の保持期間（日）
INTERACTION_HISTORY_DAYS: int = 90

# 関係強度の減衰率（日あたり）
STRENGTH_DECAY_RATE: float = 0.01

# 信頼度の減衰率（日あたり）
TRUST_DECAY_RATE: float = 0.005

# 最小インタラクション数（関係性を確立するため）
MIN_INTERACTIONS_FOR_RELATIONSHIP: int = 3

# 関係強度の増加量（インタラクションあたり）
STRENGTH_INCREMENT: float = 0.05

# 信頼度の増加量（ポジティブなインタラクションあたり）
TRUST_INCREMENT: float = 0.03

# キャッシュのTTL（秒）
GRAPH_CACHE_TTL: int = 300


# =============================================================================
# 列挙型
# =============================================================================

class RelationshipType(str, Enum):
    """関係の種類"""

    REPORTS_TO = "reports_to"                  # 上司-部下関係
    MENTORS = "mentors"                        # メンター-メンティー関係
    COLLABORATES_WITH = "collaborates_with"   # 協力関係
    CONFLICTS_WITH = "conflicts_with"          # 対立関係
    PEERS_WITH = "peers_with"                  # 同僚関係
    SUPPORTS = "supports"                      # サポート関係
    SUPERVISES = "supervises"                  # 監督関係
    CONSULTS = "consults"                      # 相談関係


class CommunicationStyle(str, Enum):
    """コミュニケーションスタイル"""

    FORMAL = "formal"           # フォーマル
    CASUAL = "casual"           # カジュアル
    DETAILED = "detailed"       # 詳細志向
    BRIEF = "brief"             # 簡潔志向
    EMPATHETIC = "empathetic"   # 共感的
    ANALYTICAL = "analytical"   # 分析的
    DIRECTIVE = "directive"     # 指示的
    COLLABORATIVE = "collaborative"  # 協調的


class InteractionType(str, Enum):
    """インタラクションの種類"""

    MESSAGE = "message"                # メッセージ送受信
    TASK_ASSIGNMENT = "task_assignment"  # タスク割り当て
    TASK_COMPLETION = "task_completion"  # タスク完了
    MENTION = "mention"                # メンション
    PRAISE = "praise"                  # 称賛
    CRITICISM = "criticism"            # 批判
    HELP_REQUEST = "help_request"      # 助けを求める
    HELP_PROVIDE = "help_provide"      # 助けを提供
    CONFLICT = "conflict"              # 対立
    RESOLUTION = "resolution"          # 解決


class ExpertiseArea(str, Enum):
    """専門領域"""

    MANAGEMENT = "management"          # 管理
    TECHNICAL = "technical"            # 技術
    SALES = "sales"                    # 営業
    MARKETING = "marketing"            # マーケティング
    FINANCE = "finance"                # 財務
    HR = "hr"                          # 人事
    LEGAL = "legal"                    # 法務
    OPERATIONS = "operations"          # 業務
    CUSTOMER_SUCCESS = "customer_success"  # カスタマーサクセス
    PRODUCT = "product"                # プロダクト


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class PersonNode:
    """
    組織グラフの人物ノード
    """
    # 識別情報
    id: str = field(default_factory=lambda: str(uuid4()))
    organization_id: str = ""
    person_id: str = ""              # users テーブルの ID

    # 基本情報
    name: str = ""
    department_id: Optional[str] = None
    role: Optional[str] = None

    # 属性
    influence_score: float = INFLUENCE_SCORE_DEFAULT
    expertise_areas: List[str] = field(default_factory=list)
    communication_style: CommunicationStyle = CommunicationStyle.CASUAL

    # 統計情報
    total_interactions: int = 0
    avg_response_time_hours: Optional[float] = None
    activity_level: float = 0.5      # 0.0〜1.0（アクティブさ）

    # タイムスタンプ
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "person_id": self.person_id,
            "name": self.name,
            "department_id": self.department_id,
            "role": self.role,
            "influence_score": self.influence_score,
            "expertise_areas": self.expertise_areas,
            "communication_style": self.communication_style.value if isinstance(self.communication_style, CommunicationStyle) else self.communication_style,
            "total_interactions": self.total_interactions,
            "activity_level": self.activity_level,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class PersonRelationship:
    """
    人物間の関係
    """
    # 識別情報
    id: str = field(default_factory=lambda: str(uuid4()))
    organization_id: str = ""

    # 関係する人物
    person_a_id: str = ""            # 関係の主体
    person_b_id: str = ""            # 関係の対象

    # 関係の種類と強さ
    relationship_type: RelationshipType = RelationshipType.COLLABORATES_WITH
    strength: float = RELATIONSHIP_STRENGTH_DEFAULT
    trust_level: float = TRUST_LEVEL_DEFAULT

    # 双方向かどうか
    bidirectional: bool = False

    # エビデンス
    observed_interactions: int = 0
    positive_interactions: int = 0
    negative_interactions: int = 0
    last_interaction_at: Optional[datetime] = None
    last_interaction_type: Optional[InteractionType] = None

    # 備考
    notes: Optional[str] = None

    # タイムスタンプ
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "person_a_id": self.person_a_id,
            "person_b_id": self.person_b_id,
            "relationship_type": self.relationship_type.value if isinstance(self.relationship_type, RelationshipType) else self.relationship_type,
            "strength": self.strength,
            "trust_level": self.trust_level,
            "bidirectional": self.bidirectional,
            "observed_interactions": self.observed_interactions,
            "positive_interactions": self.positive_interactions,
            "negative_interactions": self.negative_interactions,
            "last_interaction_at": self.last_interaction_at.isoformat() if self.last_interaction_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class Interaction:
    """
    インタラクションの記録
    """
    # 識別情報
    id: str = field(default_factory=lambda: str(uuid4()))
    organization_id: str = ""

    # 参加者
    from_person_id: str = ""
    to_person_id: str = ""

    # インタラクションの詳細
    interaction_type: InteractionType = InteractionType.MESSAGE
    sentiment: float = 0.0           # -1.0〜1.0（ネガティブ〜ポジティブ）
    context: Optional[str] = None    # コンテキスト（会話内容の要約等）

    # メタデータ
    room_id: Optional[str] = None
    message_id: Optional[str] = None

    # タイムスタンプ
    occurred_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "from_person_id": self.from_person_id,
            "to_person_id": self.to_person_id,
            "interaction_type": self.interaction_type.value if isinstance(self.interaction_type, InteractionType) else self.interaction_type,
            "sentiment": self.sentiment,
            "context": self.context,
            "room_id": self.room_id,
            "occurred_at": self.occurred_at.isoformat(),
        }


@dataclass
class OrganizationGraphStats:
    """
    組織グラフの統計情報
    """
    organization_id: str = ""

    # ノード統計
    total_persons: int = 0
    avg_influence_score: float = 0.0
    expertise_distribution: Dict[str, int] = field(default_factory=dict)
    style_distribution: Dict[str, int] = field(default_factory=dict)

    # 関係統計
    total_relationships: int = 0
    avg_relationship_strength: float = 0.0
    avg_trust_level: float = 0.0
    relationship_type_distribution: Dict[str, int] = field(default_factory=dict)

    # ネットワーク指標
    graph_density: float = 0.0       # エッジ数 / 最大可能エッジ数
    avg_connections_per_person: float = 0.0
    most_connected_person_id: Optional[str] = None
    most_influential_person_id: Optional[str] = None

    # 計算日時
    calculated_at: datetime = field(default_factory=datetime.now)


@dataclass
class RelationshipInsight:
    """
    関係性についての洞察
    """
    # 関係の識別
    person_a_id: str = ""
    person_b_id: str = ""

    # 洞察内容
    insight_type: str = ""           # "strong_bond", "deteriorating", "potential_conflict", etc.
    description: str = ""
    confidence: float = 0.0

    # 推奨アクション
    recommendations: List[str] = field(default_factory=list)

    # メタデータ
    generated_at: datetime = field(default_factory=datetime.now)


# =============================================================================
# OrganizationGraph クラス
# =============================================================================

class OrganizationGraph:
    """
    組織グラフ管理システム

    人間関係、力学、信頼関係を理解し、適切な対応をするための
    組織構造をグラフとしてモデル化するシステム。

    Attributes:
        pool: データベース接続プール
        organization_id: 組織ID
        enable_auto_learn: インタラクションから自動学習するか
    """

    def __init__(
        self,
        pool=None,
        organization_id: str = "",
        enable_auto_learn: bool = True,
    ):
        """
        OrganizationGraph を初期化

        Args:
            pool: データベース接続プール
            organization_id: 組織ID
            enable_auto_learn: インタラクションから自動学習するか
        """
        self.pool = pool
        self.organization_id = organization_id
        self.enable_auto_learn = enable_auto_learn

        # キャッシュ
        self._person_cache: Dict[str, PersonNode] = {}
        self._relationship_cache: Dict[str, PersonRelationship] = {}
        self._cache_timestamp: Optional[datetime] = None
        self._load_attempted: bool = False  # Phase 3.5: 重複ロード防止フラグ

        # インタラクションバッファ
        self._interaction_buffer: List[Interaction] = []
        self._buffer_max_size: int = 50

        logger.debug(
            f"OrganizationGraph initialized: "
            f"org_id={organization_id}, "
            f"auto_learn={enable_auto_learn}"
        )

    # =========================================================================
    # 人物ノード管理
    # =========================================================================

    async def get_person(self, person_id: str) -> Optional[PersonNode]:
        """
        人物ノードを取得

        Args:
            person_id: 人物ID（users テーブルの ID）

        Returns:
            人物ノード（見つからない場合は None）
        """
        # キャッシュから検索
        if person_id in self._person_cache:
            return self._person_cache[person_id]

        # DBから検索
        if self.pool:
            try:
                from sqlalchemy import text as sa_text
                import asyncio

                def _sync_fetch():
                    with self.pool.connect() as conn:
                        return conn.execute(
                            sa_text("""
                                SELECT id, person_id, name, department_id, role,
                                       influence_score, expertise_areas,
                                       communication_style, total_interactions,
                                       avg_response_time_hours, activity_level,
                                       created_at, updated_at
                                FROM brain_person_nodes
                                WHERE organization_id = :org_id::uuid
                                  AND person_id = :pid
                            """),
                            {"org_id": self.organization_id, "pid": person_id},
                        ).mappings().first()

                row = await asyncio.to_thread(_sync_fetch)
                if row:
                    person = PersonNode(
                        id=str(row["id"]),
                        organization_id=self.organization_id,
                        person_id=row["person_id"],
                        name=row["name"] or "",
                        department_id=row["department_id"],
                        role=row["role"],
                        influence_score=float(row["influence_score"] or 0.5),
                        expertise_areas=row["expertise_areas"] or [],
                        communication_style=CommunicationStyle(
                            row["communication_style"] or "casual"
                        ),
                        total_interactions=int(row["total_interactions"] or 0),
                        avg_response_time_hours=(
                            float(row["avg_response_time_hours"])
                            if row["avg_response_time_hours"] else None
                        ),
                        activity_level=float(row["activity_level"] or 0.5),
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                    self._person_cache[person_id] = person
                    return person
            except Exception as e:
                logger.warning("[OrganizationGraph] Error fetching person from DB: %s", type(e).__name__)

        return None

    async def upsert_person(self, person: PersonNode) -> bool:
        """
        人物ノードを追加/更新

        Args:
            person: 人物ノード

        Returns:
            成功したか
        """
        try:
            person.organization_id = self.organization_id
            person.updated_at = datetime.now()

            self._person_cache[person.person_id] = person

            # DBへの保存
            if self.pool:
                try:
                    from sqlalchemy import text as sa_text
                    import json as _json
                    import asyncio

                    def _sync_upsert():
                        with self.pool.connect() as conn:
                            conn.execute(
                                sa_text("""
                                    INSERT INTO brain_person_nodes
                                        (organization_id, person_id, name,
                                         department_id, role, influence_score,
                                         expertise_areas, communication_style,
                                         total_interactions, activity_level)
                                    VALUES
                                        (:org_id::uuid, :pid, :name,
                                         :dept, :role, :influence,
                                         :expertise::jsonb, :style,
                                         :interactions, :activity)
                                    ON CONFLICT (organization_id, person_id)
                                    DO UPDATE SET
                                        name = EXCLUDED.name,
                                        department_id = EXCLUDED.department_id,
                                        role = EXCLUDED.role,
                                        influence_score = EXCLUDED.influence_score,
                                        expertise_areas = EXCLUDED.expertise_areas,
                                        communication_style = EXCLUDED.communication_style,
                                        total_interactions = EXCLUDED.total_interactions,
                                        activity_level = EXCLUDED.activity_level
                                """),
                                {
                                    "org_id": self.organization_id,
                                    "pid": person.person_id,
                                    "name": person.name,
                                    "dept": person.department_id,
                                    "role": person.role,
                                    "influence": person.influence_score,
                                    "expertise": _json.dumps(person.expertise_areas),
                                    "style": person.communication_style.value,
                                    "interactions": person.total_interactions,
                                    "activity": person.activity_level,
                                },
                            )
                            conn.commit()

                    await asyncio.to_thread(_sync_upsert)
                except Exception as e:
                    logger.warning("[OrganizationGraph] Person DB save failed: %s", type(e).__name__)

            logger.debug(
                f"[OrganizationGraph] Person upserted: "
                f"id={person.person_id}, name={person.name}"
            )

            return True

        except Exception as e:
            logger.error(f"[OrganizationGraph] Error upserting person: {type(e).__name__}")
            return False

    async def update_person_influence(
        self,
        person_id: str,
        influence_delta: float,
    ) -> bool:
        """
        人物の影響力スコアを更新

        Args:
            person_id: 人物ID
            influence_delta: 影響力の変化量

        Returns:
            成功したか
        """
        person = await self.get_person(person_id)
        if not person:
            return False

        new_score = max(
            INFLUENCE_SCORE_MIN,
            min(INFLUENCE_SCORE_MAX, person.influence_score + influence_delta)
        )

        person.influence_score = new_score
        person.updated_at = datetime.now()

        return await self.upsert_person(person)

    async def update_person_expertise(
        self,
        person_id: str,
        expertise_areas: List[str],
    ) -> bool:
        """
        人物の専門領域を更新

        Args:
            person_id: 人物ID
            expertise_areas: 専門領域のリスト

        Returns:
            成功したか
        """
        person = await self.get_person(person_id)
        if not person:
            return False

        # 既存の専門領域とマージ
        existing = set(person.expertise_areas)
        existing.update(expertise_areas)
        person.expertise_areas = list(existing)
        person.updated_at = datetime.now()

        return await self.upsert_person(person)

    async def update_person_style(
        self,
        person_id: str,
        style: CommunicationStyle,
    ) -> bool:
        """
        人物のコミュニケーションスタイルを更新

        Args:
            person_id: 人物ID
            style: コミュニケーションスタイル

        Returns:
            成功したか
        """
        person = await self.get_person(person_id)
        if not person:
            return False

        person.communication_style = style
        person.updated_at = datetime.now()

        return await self.upsert_person(person)

    async def get_all_persons(self) -> List[PersonNode]:
        """
        全人物ノードを取得

        Returns:
            人物ノードのリスト
        """
        # キャッシュから返す
        return list(self._person_cache.values())

    # =========================================================================
    # 関係管理
    # =========================================================================

    async def get_relationship(
        self,
        person_a_id: str,
        person_b_id: str,
    ) -> Optional[PersonRelationship]:
        """
        関係を取得

        Args:
            person_a_id: 人物AのID
            person_b_id: 人物BのID

        Returns:
            関係（見つからない場合は None）
        """
        # キャッシュキーを生成
        cache_key = self._make_relationship_key(person_a_id, person_b_id)

        # キャッシュから検索
        if cache_key in self._relationship_cache:
            return self._relationship_cache[cache_key]

        # 逆方向もチェック
        reverse_key = self._make_relationship_key(person_b_id, person_a_id)
        if reverse_key in self._relationship_cache:
            rel = self._relationship_cache[reverse_key]
            if rel.bidirectional:
                return rel

        return None

    async def upsert_relationship(self, relationship: PersonRelationship) -> bool:
        """
        関係を追加/更新

        Args:
            relationship: 関係

        Returns:
            成功したか
        """
        try:
            relationship.organization_id = self.organization_id
            relationship.updated_at = datetime.now()

            cache_key = self._make_relationship_key(
                relationship.person_a_id,
                relationship.person_b_id
            )
            self._relationship_cache[cache_key] = relationship

            # DBへの保存
            if self.pool:
                try:
                    from sqlalchemy import text as sa_text
                    import json as _json
                    import asyncio

                    def _sync_upsert_rel():
                        with self.pool.connect() as conn:
                            conn.execute(
                                sa_text("""
                                    INSERT INTO brain_relationships
                                        (organization_id, person_a_id, person_b_id,
                                         relationship_type, strength, trust_level,
                                         bidirectional, interaction_count, context)
                                    VALUES
                                        (:org_id::uuid, :a_id, :b_id,
                                         :rel_type, :strength, :trust,
                                         :bidir, :count, :ctx::jsonb)
                                    ON CONFLICT (organization_id, person_a_id, person_b_id, relationship_type)
                                    DO UPDATE SET
                                        strength = EXCLUDED.strength,
                                        trust_level = EXCLUDED.trust_level,
                                        interaction_count = EXCLUDED.interaction_count,
                                        context = EXCLUDED.context
                                """),
                                {
                                    "org_id": self.organization_id,
                                    "a_id": relationship.person_a_id,
                                    "b_id": relationship.person_b_id,
                                    "rel_type": relationship.relationship_type.value,
                                    "strength": relationship.strength,
                                    "trust": relationship.trust_level,
                                    "bidir": relationship.bidirectional,
                                    "count": relationship.observed_interactions,
                                    "ctx": _json.dumps({"notes": relationship.notes} if relationship.notes else {}),
                                },
                            )
                            conn.commit()

                    await asyncio.to_thread(_sync_upsert_rel)
                except Exception as e:
                    logger.warning("[OrganizationGraph] Relationship DB save failed: %s", type(e).__name__)

            logger.debug(
                f"[OrganizationGraph] Relationship upserted: "
                f"{relationship.person_a_id} -> {relationship.person_b_id} "
                f"({relationship.relationship_type.value})"
            )

            return True

        except Exception as e:
            logger.error(f"[OrganizationGraph] Error upserting relationship: {type(e).__name__}")
            return False

    async def get_relationships_for_person(
        self,
        person_id: str,
        relationship_type: Optional[RelationshipType] = None,
    ) -> List[PersonRelationship]:
        """
        特定の人物の全関係を取得

        Args:
            person_id: 人物ID
            relationship_type: 関係タイプ（指定時はフィルタ）

        Returns:
            関係のリスト
        """
        relationships: List[PersonRelationship] = []

        for rel in self._relationship_cache.values():
            # 主体または対象（双方向の場合）
            if rel.person_a_id == person_id or (rel.bidirectional and rel.person_b_id == person_id):
                if relationship_type is None or rel.relationship_type == relationship_type:
                    relationships.append(rel)

        return relationships

    async def get_direct_reports(self, manager_id: str) -> List[str]:
        """
        直属の部下を取得

        Args:
            manager_id: マネージャーのID

        Returns:
            部下のIDリスト
        """
        direct_reports: List[str] = []

        for rel in self._relationship_cache.values():
            if (rel.relationship_type == RelationshipType.REPORTS_TO and
                rel.person_b_id == manager_id):
                direct_reports.append(rel.person_a_id)

        return direct_reports

    async def get_manager(self, person_id: str) -> Optional[str]:
        """
        マネージャーを取得

        Args:
            person_id: 人物ID

        Returns:
            マネージャーのID（いない場合は None）
        """
        for rel in self._relationship_cache.values():
            if (rel.relationship_type == RelationshipType.REPORTS_TO and
                rel.person_a_id == person_id):
                return rel.person_b_id

        return None

    async def get_collaborators(self, person_id: str) -> List[str]:
        """
        協力者を取得

        Args:
            person_id: 人物ID

        Returns:
            協力者のIDリスト
        """
        collaborators: List[str] = []

        for rel in self._relationship_cache.values():
            if rel.relationship_type == RelationshipType.COLLABORATES_WITH:
                if rel.person_a_id == person_id:
                    collaborators.append(rel.person_b_id)
                elif rel.bidirectional and rel.person_b_id == person_id:
                    collaborators.append(rel.person_a_id)

        return collaborators

    # =========================================================================
    # インタラクション記録と学習
    # =========================================================================

    async def record_interaction(self, interaction: Interaction) -> bool:
        """
        インタラクションを記録

        Args:
            interaction: インタラクション

        Returns:
            成功したか
        """
        try:
            interaction.organization_id = self.organization_id
            self._interaction_buffer.append(interaction)

            # バッファがいっぱいになったらフラッシュ
            if len(self._interaction_buffer) >= self._buffer_max_size:
                await self._flush_interaction_buffer()

            # 自動学習が有効なら関係性を更新
            if self.enable_auto_learn:
                await self._learn_from_interaction(interaction)

            logger.debug(
                f"[OrganizationGraph] Interaction recorded: "
                f"{interaction.from_person_id} -> {interaction.to_person_id} "
                f"({interaction.interaction_type.value})"
            )

            return True

        except Exception as e:
            logger.error(f"[OrganizationGraph] Error recording interaction: {type(e).__name__}")
            return False

    async def _learn_from_interaction(self, interaction: Interaction) -> bool:
        """
        インタラクションから学習

        Args:
            interaction: インタラクション

        Returns:
            学習が行われたか
        """
        try:
            # 既存の関係を取得または新規作成
            relationship = await self.get_relationship(
                interaction.from_person_id,
                interaction.to_person_id
            )

            if not relationship:
                # 新規関係を作成
                relationship = PersonRelationship(
                    organization_id=self.organization_id,
                    person_a_id=interaction.from_person_id,
                    person_b_id=interaction.to_person_id,
                    relationship_type=self._infer_relationship_type(interaction),
                    bidirectional=True,  # 一般的に双方向
                )

            # インタラクション数を更新
            relationship.observed_interactions += 1
            relationship.last_interaction_at = interaction.occurred_at
            relationship.last_interaction_type = interaction.interaction_type

            # センチメントに基づいて統計を更新
            if interaction.sentiment > 0.2:
                relationship.positive_interactions += 1
            elif interaction.sentiment < -0.2:
                relationship.negative_interactions += 1

            # 関係強度を更新
            relationship.strength = min(
                RELATIONSHIP_STRENGTH_MAX,
                relationship.strength + STRENGTH_INCREMENT
            )

            # 信頼度を更新（ポジティブなインタラクションで上昇）
            if interaction.sentiment > 0:
                relationship.trust_level = min(
                    TRUST_LEVEL_MAX,
                    relationship.trust_level + TRUST_INCREMENT * interaction.sentiment
                )
            elif interaction.sentiment < 0:
                relationship.trust_level = max(
                    TRUST_LEVEL_MIN,
                    relationship.trust_level + TRUST_INCREMENT * interaction.sentiment
                )

            # 関係タイプを推論（インタラクションタイプに基づいて更新の可能性）
            inferred_type = self._infer_relationship_type(interaction)
            if self._should_update_relationship_type(relationship, inferred_type, interaction):
                relationship.relationship_type = inferred_type

            await self.upsert_relationship(relationship)

            # 人物のインタラクション数を更新
            from_person = await self.get_person(interaction.from_person_id)
            if from_person:
                from_person.total_interactions += 1
                await self.upsert_person(from_person)

            return True

        except Exception as e:
            logger.error(f"[OrganizationGraph] Error learning from interaction: {type(e).__name__}")
            return False

    def _infer_relationship_type(
        self,
        interaction: Interaction,
    ) -> RelationshipType:
        """
        インタラクションから関係タイプを推論

        Args:
            interaction: インタラクション

        Returns:
            推論された関係タイプ
        """
        # インタラクションタイプに基づいて推論
        type_mapping = {
            InteractionType.TASK_ASSIGNMENT: RelationshipType.SUPERVISES,
            InteractionType.HELP_REQUEST: RelationshipType.CONSULTS,
            InteractionType.HELP_PROVIDE: RelationshipType.SUPPORTS,
            InteractionType.PRAISE: RelationshipType.COLLABORATES_WITH,
            InteractionType.CONFLICT: RelationshipType.CONFLICTS_WITH,
        }

        return type_mapping.get(
            interaction.interaction_type,
            RelationshipType.COLLABORATES_WITH
        )

    def _should_update_relationship_type(
        self,
        relationship: PersonRelationship,
        new_type: RelationshipType,
        interaction: Interaction,
    ) -> bool:
        """
        関係タイプを更新すべきか判断

        Args:
            relationship: 現在の関係
            new_type: 新しい関係タイプ
            interaction: インタラクション

        Returns:
            更新すべきか
        """
        # 対立関係は慎重に（複数回の対立が必要）
        if new_type == RelationshipType.CONFLICTS_WITH:
            if relationship.negative_interactions < 3:
                return False

        # 既存の関係タイプがより強い場合は更新しない
        strong_types = {
            RelationshipType.REPORTS_TO,
            RelationshipType.SUPERVISES,
            RelationshipType.MENTORS,
        }

        if relationship.relationship_type in strong_types and new_type not in strong_types:
            return False

        return True

    async def _flush_interaction_buffer(self) -> int:
        """
        インタラクションバッファをフラッシュ

        Returns:
            フラッシュされた数
        """
        if not self._interaction_buffer:
            return 0

        entries = list(self._interaction_buffer)
        self._interaction_buffer.clear()
        count = len(entries)

        # DBへの保存
        if self.pool and entries:
            try:
                from sqlalchemy import text as sa_text
                import asyncio

                def _sync_flush_interactions():
                    with self.pool.connect() as conn:
                        # バッチINSERT（100件チャンク）— executemanyパターン（C-2: 鉄則#9準拠）
                        insert_sql = sa_text(
                            "INSERT INTO brain_interactions"
                            " (organization_id, from_person_id,"
                            " to_person_id, interaction_type,"
                            " sentiment, room_id)"
                            " VALUES (:org_id::uuid, :from_id,"
                            " :to_id, :type,"
                            " :sentiment, :room_id)"
                        )
                        for i in range(0, len(entries), 100):
                            chunk = entries[i:i + 100]
                            rows = [
                                {
                                    "org_id": self.organization_id,
                                    "from_id": interaction.from_person_id,
                                    "to_id": interaction.to_person_id,
                                    "type": interaction.interaction_type.value,
                                    "sentiment": getattr(interaction, "sentiment", 0.0),
                                    "room_id": getattr(interaction, "room_id", None),
                                }
                                for interaction in chunk
                            ]
                            conn.execute(insert_sql, rows)
                        conn.commit()

                await asyncio.to_thread(_sync_flush_interactions)
            except Exception as e:
                logger.warning("[OrganizationGraph] Interaction flush failed: %s", type(e).__name__)

        logger.debug(f"[OrganizationGraph] Flushed {count} interactions")

        return count

    # =========================================================================
    # 減衰処理
    # =========================================================================

    async def apply_decay(self) -> int:
        """
        関係強度と信頼度の減衰を適用

        Returns:
            更新された関係の数
        """
        updated_count = 0
        now = datetime.now()

        for rel in self._relationship_cache.values():
            if rel.last_interaction_at:
                days_since = (now - rel.last_interaction_at).days

                if days_since > 0:
                    # 強度の減衰
                    new_strength = max(
                        RELATIONSHIP_STRENGTH_MIN,
                        rel.strength - (STRENGTH_DECAY_RATE * days_since)
                    )

                    # 信頼度の減衰
                    new_trust = max(
                        TRUST_LEVEL_MIN,
                        rel.trust_level - (TRUST_DECAY_RATE * days_since)
                    )

                    if new_strength != rel.strength or new_trust != rel.trust_level:
                        rel.strength = new_strength
                        rel.trust_level = new_trust
                        rel.updated_at = now
                        updated_count += 1

        logger.debug(f"[OrganizationGraph] Decay applied to {updated_count} relationships")

        return updated_count

    # =========================================================================
    # 分析と洞察
    # =========================================================================

    async def get_graph_stats(self) -> OrganizationGraphStats:
        """
        組織グラフの統計情報を取得

        Returns:
            統計情報
        """
        stats = OrganizationGraphStats(organization_id=self.organization_id)

        # ノード統計
        persons = list(self._person_cache.values())
        stats.total_persons = len(persons)

        if persons:
            stats.avg_influence_score = sum(p.influence_score for p in persons) / len(persons)

            # 専門領域の分布
            for person in persons:
                for expertise in person.expertise_areas:
                    stats.expertise_distribution[expertise] = (
                        stats.expertise_distribution.get(expertise, 0) + 1
                    )

            # スタイルの分布
            for person in persons:
                style = person.communication_style.value if isinstance(person.communication_style, CommunicationStyle) else person.communication_style
                stats.style_distribution[style] = stats.style_distribution.get(style, 0) + 1

        # 関係統計
        relationships = list(self._relationship_cache.values())
        stats.total_relationships = len(relationships)

        if relationships:
            stats.avg_relationship_strength = sum(r.strength for r in relationships) / len(relationships)
            stats.avg_trust_level = sum(r.trust_level for r in relationships) / len(relationships)

            # 関係タイプの分布
            for rel in relationships:
                rel_type = rel.relationship_type.value if isinstance(rel.relationship_type, RelationshipType) else rel.relationship_type
                stats.relationship_type_distribution[rel_type] = (
                    stats.relationship_type_distribution.get(rel_type, 0) + 1
                )

        # ネットワーク指標
        if stats.total_persons > 1:
            max_edges = stats.total_persons * (stats.total_persons - 1) / 2
            stats.graph_density = stats.total_relationships / max_edges if max_edges > 0 else 0

        if stats.total_persons > 0:
            stats.avg_connections_per_person = (
                stats.total_relationships * 2 / stats.total_persons
            )

        # 最も接続の多い人物を見つける
        connection_counts: Dict[str, int] = {}
        for rel in relationships:
            connection_counts[rel.person_a_id] = connection_counts.get(rel.person_a_id, 0) + 1
            if rel.bidirectional:
                connection_counts[rel.person_b_id] = connection_counts.get(rel.person_b_id, 0) + 1

        if connection_counts:
            stats.most_connected_person_id = max(connection_counts, key=lambda x: connection_counts.get(x, 0))

        # 最も影響力のある人物を見つける
        if persons:
            stats.most_influential_person_id = max(
                persons, key=lambda p: p.influence_score
            ).person_id

        return stats

    async def generate_relationship_insights(
        self,
        person_id: Optional[str] = None,
    ) -> List[RelationshipInsight]:
        """
        関係性についての洞察を生成

        Args:
            person_id: 特定の人物に絞る場合

        Returns:
            洞察のリスト
        """
        insights: List[RelationshipInsight] = []

        relationships = list(self._relationship_cache.values())
        if person_id:
            relationships = [
                r for r in relationships
                if r.person_a_id == person_id or r.person_b_id == person_id
            ]

        for rel in relationships:
            # 強い絆
            if rel.strength > 0.8 and rel.trust_level > 0.8:
                insights.append(RelationshipInsight(
                    person_a_id=rel.person_a_id,
                    person_b_id=rel.person_b_id,
                    insight_type="strong_bond",
                    description=f"強い絆と高い信頼関係があります",
                    confidence=0.9,
                    recommendations=[
                        "重要なプロジェクトでの協力を検討",
                        "メンタリングペアとして活用可能",
                    ],
                ))

            # 悪化している関係
            if rel.negative_interactions > rel.positive_interactions and rel.observed_interactions >= 5:
                insights.append(RelationshipInsight(
                    person_a_id=rel.person_a_id,
                    person_b_id=rel.person_b_id,
                    insight_type="deteriorating",
                    description=f"ネガティブなインタラクションが多く、関係が悪化している可能性",
                    confidence=0.7,
                    recommendations=[
                        "1on1ミーティングで状況を確認",
                        "仲介者を入れた対話の検討",
                    ],
                ))

            # 潜在的対立
            if rel.relationship_type == RelationshipType.CONFLICTS_WITH:
                insights.append(RelationshipInsight(
                    person_a_id=rel.person_a_id,
                    person_b_id=rel.person_b_id,
                    insight_type="potential_conflict",
                    description=f"対立関係が検出されています",
                    confidence=0.8,
                    recommendations=[
                        "直接の協業を避けることを検討",
                        "コンフリクト解決のサポートを検討",
                    ],
                ))

            # 弱い関係（強化の余地あり）
            if rel.strength < 0.3 and rel.observed_interactions >= MIN_INTERACTIONS_FOR_RELATIONSHIP:
                insights.append(RelationshipInsight(
                    person_a_id=rel.person_a_id,
                    person_b_id=rel.person_b_id,
                    insight_type="weak_connection",
                    description=f"関係が弱く、強化の余地があります",
                    confidence=0.6,
                    recommendations=[
                        "共同プロジェクトへの参加を促進",
                        "定期的な1on1を設定",
                    ],
                ))

        return insights

    async def find_communication_path(
        self,
        from_person_id: str,
        to_person_id: str,
    ) -> List[str]:
        """
        2人の人物間のコミュニケーションパスを見つける

        Args:
            from_person_id: 開始人物ID
            to_person_id: 終了人物ID

        Returns:
            パス（人物IDのリスト）、見つからない場合は空リスト
        """
        if from_person_id == to_person_id:
            return [from_person_id]

        # BFS で最短パスを見つける
        visited: Set[str] = set()
        queue: List[List[str]] = [[from_person_id]]

        while queue:
            path = queue.pop(0)
            current = path[-1]

            if current in visited:
                continue

            visited.add(current)

            # 隣接ノードを取得
            neighbors: Set[str] = set()
            for rel in self._relationship_cache.values():
                if rel.person_a_id == current:
                    neighbors.add(rel.person_b_id)
                if rel.bidirectional and rel.person_b_id == current:
                    neighbors.add(rel.person_a_id)

            for neighbor in neighbors:
                if neighbor == to_person_id:
                    return path + [neighbor]

                if neighbor not in visited:
                    queue.append(path + [neighbor])

        return []

    async def suggest_introducer(
        self,
        person_a_id: str,
        person_b_id: str,
    ) -> Optional[str]:
        """
        2人を紹介できる人物を提案

        Args:
            person_a_id: 人物AのID
            person_b_id: 人物BのID

        Returns:
            紹介者のID（いない場合は None）
        """
        # 両方と関係がある人物を探す
        a_connections: Set[str] = set()
        b_connections: Set[str] = set()

        for rel in self._relationship_cache.values():
            if rel.person_a_id == person_a_id or (rel.bidirectional and rel.person_b_id == person_a_id):
                target = rel.person_b_id if rel.person_a_id == person_a_id else rel.person_a_id
                a_connections.add(target)

            if rel.person_a_id == person_b_id or (rel.bidirectional and rel.person_b_id == person_b_id):
                target = rel.person_b_id if rel.person_a_id == person_b_id else rel.person_a_id
                b_connections.add(target)

        # 共通の接続を見つける
        common = a_connections & b_connections

        if not common:
            return None

        # 最も影響力のある人物を選択
        best_introducer: Optional[str] = None
        best_influence: float = -1.0

        for person_id in common:
            person = await self.get_person(person_id)
            if person and person.influence_score > best_influence:
                best_influence = person.influence_score
                best_introducer = person_id

        return best_introducer

    # =========================================================================
    # ユーティリティ
    # =========================================================================

    def _make_relationship_key(self, person_a_id: str, person_b_id: str) -> str:
        """関係のキャッシュキーを生成"""
        return f"{person_a_id}:{person_b_id}"

    async def clear_cache(self) -> None:
        """キャッシュをクリア"""
        self._person_cache.clear()
        self._relationship_cache.clear()
        self._cache_timestamp = None

        logger.debug("[OrganizationGraph] Cache cleared")

    # =========================================================================
    # Phase 3.5: 一括読み込み（DBスタブ解消）
    # =========================================================================

    async def load_from_db(self) -> None:
        """
        DBから全ノード・関係を一括読み込みしてキャッシュを初期化

        起動時または最初のリクエスト時に1回呼び出す。
        失敗しても graceful degradation（空キャッシュのまま続行）。
        """
        if not self.pool:
            return

        try:
            from sqlalchemy import text as sa_text

            def _sync_fetch():
                with self.pool.connect() as conn:
                    # W-1: RLS set_config（アプリレベルフィルタとの二重防御）
                    conn.execute(
                        sa_text(
                            "SELECT set_config('app.current_organization_id', :org_id, true)"
                        ),
                        {"org_id": self.organization_id},
                    )

                    persons = conn.execute(
                        sa_text("""
                            SELECT id, person_id, name, department_id, role,
                                   influence_score, expertise_areas,
                                   communication_style, total_interactions,
                                   avg_response_time_hours, activity_level,
                                   created_at, updated_at
                            FROM brain_person_nodes
                            WHERE organization_id = :org_id::uuid
                            ORDER BY influence_score DESC NULLS LAST
                            LIMIT 100
                        """),
                        {"org_id": self.organization_id},
                    ).mappings().all()

                    relationships = conn.execute(
                        sa_text("""
                            SELECT id, person_a_id, person_b_id, relationship_type,
                                   strength, trust_level, bidirectional,
                                   interaction_count,
                                   created_at, updated_at
                            FROM brain_relationships
                            WHERE organization_id = :org_id::uuid
                            LIMIT 200
                        """),
                        {"org_id": self.organization_id},
                    ).mappings().all()

                    return list(persons), list(relationships)

            persons_rows, rel_rows = await asyncio.to_thread(_sync_fetch)

            # キャッシュに格納（人物ノード）
            for row in persons_rows:
                try:
                    comm_style_val = row["communication_style"] or "casual"
                    try:
                        comm_style = CommunicationStyle(comm_style_val)
                    except ValueError:
                        comm_style = CommunicationStyle.CASUAL

                    person = PersonNode(
                        id=str(row["id"]),
                        organization_id=self.organization_id,
                        person_id=row["person_id"],
                        name=row["name"] or "",
                        department_id=row["department_id"],
                        role=row["role"],
                        influence_score=float(row["influence_score"] or INFLUENCE_SCORE_DEFAULT),
                        expertise_areas=row["expertise_areas"] or [],
                        communication_style=comm_style,
                        total_interactions=int(row["total_interactions"] or 0),
                        avg_response_time_hours=(
                            float(row["avg_response_time_hours"])
                            if row["avg_response_time_hours"] else None
                        ),
                        activity_level=float(row["activity_level"] or 0.5),
                        created_at=row["created_at"] or datetime.now(),
                        updated_at=row["updated_at"] or datetime.now(),
                    )
                    self._person_cache[row["person_id"]] = person
                except Exception as row_e:
                    logger.warning(
                        "[OrganizationGraph] Error parsing person row: %s", type(row_e).__name__
                    )

            # キャッシュに格納（関係）
            for row in rel_rows:
                try:
                    rel_type_val = row["relationship_type"] or "collaborates_with"
                    try:
                        rel_type = RelationshipType(rel_type_val)
                    except ValueError:
                        rel_type = RelationshipType.COLLABORATES_WITH

                    rel = PersonRelationship(
                        id=str(row["id"]),
                        organization_id=self.organization_id,
                        person_a_id=row["person_a_id"],
                        person_b_id=row["person_b_id"],
                        relationship_type=rel_type,
                        strength=float(row["strength"] or RELATIONSHIP_STRENGTH_DEFAULT),
                        trust_level=float(row["trust_level"] or TRUST_LEVEL_DEFAULT),
                        bidirectional=bool(row["bidirectional"] or False),
                        observed_interactions=int(row["interaction_count"] or 0),
                        created_at=row["created_at"] or datetime.now(),
                        updated_at=row["updated_at"] or datetime.now(),
                    )
                    key = f"{row['person_a_id']}:{row['person_b_id']}"
                    self._relationship_cache[key] = rel
                except Exception as row_e:
                    logger.warning(
                        "[OrganizationGraph] Error parsing relationship row: %s", type(row_e).__name__
                    )

            self._cache_timestamp = datetime.now()
            self._load_attempted = True
            logger.info(
                "[OrganizationGraph] load_from_db: %d persons, %d relationships loaded",
                len(persons_rows), len(rel_rows),
            )

        except Exception as e:
            self._load_attempted = True  # 失敗してもリトライしない（graceful degradation）
            logger.warning("[OrganizationGraph] load_from_db failed (graceful): %s", type(e).__name__)

    # =========================================================================
    # Phase 3.5: コンテキスト生成用ヘルパー
    # =========================================================================

    def get_top_persons_by_influence(self, limit: int = 5) -> List[PersonNode]:
        """影響力スコアが高い人物をキャッシュから返す"""
        persons = sorted(
            self._person_cache.values(),
            key=lambda p: p.influence_score,
            reverse=True,
        )
        return persons[:limit]

    def get_cached_relationships_for_person(self, person_id: str) -> List[PersonRelationship]:
        """特定人物の関係をキャッシュから返す（同期版・Phase 3.5 context_builder用）"""
        return [
            rel for rel in self._relationship_cache.values()
            if rel.person_a_id == person_id or rel.person_b_id == person_id
        ]

    def get_strong_relationships(
        self, min_strength: float = 0.7, limit: int = 5
    ) -> List[PersonRelationship]:
        """一定強度以上の関係をソート済みで返す（W-2: context_builder用公開API）"""
        strong_rels = sorted(
            [r for r in self._relationship_cache.values() if r.strength >= min_strength],
            key=lambda r: r.strength,
            reverse=True,
        )
        return strong_rels[:limit]

    def get_person_by_id(self, person_id: str) -> Optional[PersonNode]:
        """キャッシュから人物を取得（W-2: context_builder用公開API）"""
        return self._person_cache.get(person_id)

    def is_cache_loaded(self) -> bool:
        """キャッシュのロード状態を返す（W-2: context_builder用公開API）"""
        return bool(self._person_cache) or self._load_attempted


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_organization_graph(
    pool=None,
    organization_id: str = "",
    enable_auto_learn: bool = True,
) -> OrganizationGraph:
    """
    OrganizationGraph インスタンスを作成

    Args:
        pool: データベース接続プール
        organization_id: 組織ID
        enable_auto_learn: インタラクションから自動学習するか

    Returns:
        OrganizationGraph
    """
    return OrganizationGraph(
        pool=pool,
        organization_id=organization_id,
        enable_auto_learn=enable_auto_learn,
    )
