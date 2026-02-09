"""
ナレッジ管理ハンドラー

main.pyから分割されたナレッジ管理機能を提供する。
旧システム（soulkun_knowledge）とPhase 3（Pinecone）の統合検索も含む。

分割元: chatwork-webhook/main.py
分割日: 2026-01-25
バージョン: v10.24.7
"""

import httpx
import traceback
import sqlalchemy
from typing import Optional, List, Dict, Any, Callable, Union

from lib.brain.hybrid_search import escape_ilike


# =====================================================
# 定数: キーワード・クエリ拡張
# =====================================================

# 業務関連キーワード辞書
KNOWLEDGE_KEYWORDS = [
    # 休暇関連
    "有給休暇", "有給", "年休", "年次有給休暇", "休暇", "休み",
    "特別休暇", "慶弔休暇", "産休", "育休", "介護休暇",
    # 賃金関連
    "賞与", "ボーナス", "給与", "賃金", "手当", "基本給",
    "残業代", "時間外手当", "深夜手当", "休日手当",
    # 勤務関連
    "残業", "時間外労働", "勤務時間", "休日", "労働時間",
    "始業", "終業", "休憩", "フレックス",
    # 福利厚生
    "経費", "精算", "交通費", "出張",
    # 人事関連
    "退職", "休職", "異動", "昇給", "昇格", "評価",
    # 規則関連
    "就業規則", "服務規律", "懲戒", "解雇",
]

# クエリ拡張辞書（エンベディングモデルが理解しやすいフレーズに展開）
QUERY_EXPANSION_MAP = {
    # 有給休暇関連
    "有給休暇": "年次有給休暇 付与日数 入社6か月後 10日 勤続年数",
    "有給": "年次有給休暇 付与日数 入社6か月後 10日 勤続年数",
    "年休": "年次有給休暇 付与日数 入社6か月後 10日 勤続年数",
    # 賞与関連
    "賞与": "賞与 ボーナス 支給 算定期間 支給日",
    "ボーナス": "賞与 ボーナス 支給 算定期間 支給日",
    # 残業関連
    "残業": "時間外労働 残業 割増賃金 36協定 上限",
    # 退職関連
    "退職": "退職 退職届 退職金 予告期間 14日前",
}

# 知識の上限設定（トークン制限対策）
KNOWLEDGE_LIMIT = 50  # プロンプトに含める知識の最大件数
KNOWLEDGE_VALUE_MAX_LENGTH = 200  # 各知識の値の最大文字数


class KnowledgeHandler:
    """
    ナレッジの管理・検索を行うハンドラークラス

    外部依存を注入することで、main.pyとの疎結合を実現。
    """

    def __init__(
        self,
        get_pool: Callable,
        is_admin_func: Callable = None,
        create_proposal_func: Callable = None,
        report_proposal_to_admin_func: Callable = None,
        is_mvv_question_func: Callable = None,
        get_full_mvv_info_func: Callable = None,
        phase3_knowledge_config: Dict[str, Any] = None,
        admin_account_id: str = None,
    ):
        """
        Args:
            get_pool: DB接続プールを取得する関数
            is_admin_func: 管理者判定関数
            create_proposal_func: 提案作成関数
            report_proposal_to_admin_func: 管理部への報告関数
            is_mvv_question_func: MVV質問判定関数
            get_full_mvv_info_func: MVV情報取得関数
            phase3_knowledge_config: Phase 3ナレッジ検索設定
            admin_account_id: 管理者アカウントID
        """
        self.get_pool = get_pool
        self.is_admin_func = is_admin_func
        self.create_proposal_func = create_proposal_func
        self.report_proposal_to_admin_func = report_proposal_to_admin_func
        self.is_mvv_question_func = is_mvv_question_func
        self.get_full_mvv_info_func = get_full_mvv_info_func
        self.phase3_config = phase3_knowledge_config or {}
        self.admin_account_id = admin_account_id
        # Phase 4: org_id for soulkun_knowledge queries
        self.organization_id = self.phase3_config.get("organization_id", "org_soulsyncs")

    # =====================================================
    # キーワード・クエリ処理（静的メソッド）
    # =====================================================

    @staticmethod
    def extract_keywords(query: str) -> List[str]:
        """
        クエリからキーワードを抽出

        Args:
            query: 検索クエリ

        Returns:
            抽出されたキーワードのリスト
        """
        keywords = []
        for keyword in KNOWLEDGE_KEYWORDS:
            if keyword in query:
                keywords.append(keyword)
        # 短縮形の展開
        expansions = {
            "有給": ["有給休暇", "年次有給休暇"],
            "年休": ["年次有給休暇"],
            "残業": ["時間外労働"],
            "ボーナス": ["賞与"],
        }
        for short_form, long_forms in expansions.items():
            if short_form in keywords:
                for long_form in long_forms:
                    if long_form not in keywords:
                        keywords.append(long_form)
        return keywords

    @staticmethod
    def expand_query(query: str, keywords: List[str]) -> str:
        """
        クエリを拡張して検索精度を向上

        Args:
            query: 元のクエリ
            keywords: 抽出されたキーワード

        Returns:
            拡張されたクエリ
        """
        if not keywords:
            return query
        for keyword in keywords:
            if keyword in QUERY_EXPANSION_MAP:
                expansion = QUERY_EXPANSION_MAP[keyword]
                expanded = f"{query} {expansion}"
                print(f"🔧 クエリ拡張: '{query}' → '{expanded}'")
                return expanded
        return query

    @staticmethod
    def calculate_keyword_score(content: str, keywords: List[str]) -> float:
        """
        コンテンツに対するキーワードスコアを計算

        Args:
            content: 検索対象のコンテンツ
            keywords: キーワードリスト

        Returns:
            キーワードスコア（0.0〜1.0）
        """
        if not keywords or not content:
            return 0.0
        score = 0.0
        for keyword in keywords:
            if keyword in content:
                count = min(content.count(keyword), 3)
                score += 0.25 * count
        return min(score, 1.0)

    # =====================================================
    # データベース操作
    # =====================================================

    def ensure_knowledge_tables(self) -> None:
        """管理者学習機能用テーブルが存在しない場合は作成"""
        try:
            pool = self.get_pool()
            with pool.begin() as conn:
                # 知識テーブル
                conn.execute(sqlalchemy.text("""
                    CREATE TABLE IF NOT EXISTS soulkun_knowledge (
                        id SERIAL PRIMARY KEY,
                        organization_id VARCHAR(255) NOT NULL DEFAULT 'org_soulsyncs',
                        category TEXT NOT NULL DEFAULT 'other',
                        key TEXT NOT NULL,
                        value TEXT NOT NULL,
                        created_by TEXT,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(organization_id, category, key)
                    );
                """))
                conn.execute(sqlalchemy.text("""
                    CREATE INDEX IF NOT EXISTS idx_knowledge_category
                    ON soulkun_knowledge(category);
                """))

                # 提案テーブル（Phase 4: org_idカラム追加）
                conn.execute(sqlalchemy.text("""
                    CREATE TABLE IF NOT EXISTS knowledge_proposals (
                        id SERIAL PRIMARY KEY,
                        organization_id VARCHAR(255) NOT NULL DEFAULT 'org_soulsyncs',
                        proposed_by_account_id TEXT NOT NULL,
                        proposed_by_name TEXT,
                        proposed_in_room_id TEXT,
                        category TEXT NOT NULL DEFAULT 'other',
                        key TEXT NOT NULL,
                        value TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        message_id TEXT,
                        admin_message_id TEXT,
                        admin_notified BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        reviewed_by TEXT,
                        reviewed_at TIMESTAMP WITH TIME ZONE
                    );
                """))
                # v6.9.1: 既存テーブルにカラム追加（マイグレーション用）
                try:
                    conn.execute(sqlalchemy.text("""
                        ALTER TABLE knowledge_proposals
                        ADD COLUMN IF NOT EXISTS admin_notified BOOLEAN DEFAULT FALSE;
                    """))
                except:
                    pass  # カラム既存の場合は無視
                conn.execute(sqlalchemy.text("""
                    CREATE INDEX IF NOT EXISTS idx_proposals_status
                    ON knowledge_proposals(status);
                """))

                print("✅ 管理者学習機能テーブルの確認/作成完了")
        except Exception as e:
            print(f"⚠️ 管理者学習機能テーブル作成エラー: {e}")
            traceback.print_exc()

    def save_knowledge(self, category: str, key: str, value: str, created_by: str = None) -> bool:
        """
        知識を保存（既存の場合は更新）

        Args:
            category: カテゴリ
            key: キー
            value: 値
            created_by: 作成者ID

        Returns:
            成功時True、失敗時False
        """
        try:
            pool = self.get_pool()
            with pool.begin() as conn:
                # UPSERT（存在すれば更新、なければ挿入）
                conn.execute(sqlalchemy.text("""
                    INSERT INTO soulkun_knowledge (organization_id, category, key, value, created_by, updated_at)
                    VALUES (:org_id, :category, :key, :value, :created_by, CURRENT_TIMESTAMP)
                    ON CONFLICT (organization_id, category, key)
                    DO UPDATE SET value = :value, updated_at = CURRENT_TIMESTAMP
                """), {
                    "org_id": self.organization_id,
                    "category": category,
                    "key": key,
                    "value": value,
                    "created_by": created_by
                })
            print(f"✅ 知識を保存: [{category}] {key} = {value}")
            return True
        except Exception as e:
            print(f"❌ 知識保存エラー: {e}")
            traceback.print_exc()
            return False

    def delete_knowledge(self, category: str = None, key: str = None) -> bool:
        """
        知識を削除

        Args:
            category: カテゴリ（オプション）
            key: キー

        Returns:
            成功時True、失敗時False
        """
        try:
            pool = self.get_pool()
            with pool.begin() as conn:
                if category and key:
                    conn.execute(sqlalchemy.text("""
                        DELETE FROM soulkun_knowledge
                        WHERE organization_id = :org_id AND category = :category AND key = :key
                    """), {"org_id": self.organization_id, "category": category, "key": key})
                elif key:
                    conn.execute(sqlalchemy.text("""
                        DELETE FROM soulkun_knowledge
                        WHERE organization_id = :org_id AND key = :key
                    """), {"org_id": self.organization_id, "key": key})
            print(f"✅ 知識を削除: [{category}] {key}")
            return True
        except Exception as e:
            print(f"❌ 知識削除エラー: {e}")
            traceback.print_exc()
            return False

    def get_all_knowledge(self, limit: int = None) -> List[Dict[str, Any]]:
        """
        全ての知識を取得

        Args:
            limit: 取得件数の上限

        Returns:
            知識のリスト
        """
        try:
            pool = self.get_pool()
            with pool.connect() as conn:
                sql = """
                    SELECT category, key, value, created_at
                    FROM soulkun_knowledge
                    WHERE organization_id = :org_id
                    ORDER BY category, updated_at DESC
                """
                params = {"org_id": self.organization_id}
                if limit:
                    sql += " LIMIT :limit"
                    params["limit"] = limit
                result = conn.execute(sqlalchemy.text(sql), params)
                rows = result.fetchall()
                return [{"category": r[0], "key": r[1], "value": r[2], "created_at": r[3]} for r in rows]
        except Exception as e:
            print(f"❌ 知識取得エラー: {e}")
            traceback.print_exc()
            return []

    def get_knowledge_for_prompt(self) -> str:
        """
        プロンプト用に知識を整形して取得（上限付き）

        Returns:
            整形された知識テキスト
        """
        # v6.9.1: 上限を設定
        knowledge_list = self.get_all_knowledge(limit=KNOWLEDGE_LIMIT)
        if not knowledge_list:
            return ""

        # カテゴリごとにグループ化
        by_category = {}
        for k in knowledge_list:
            cat = k["category"]
            if cat not in by_category:
                by_category[cat] = []
            # v6.9.1: 値の長さを制限
            value = k['value']
            if len(value) > KNOWLEDGE_VALUE_MAX_LENGTH:
                value = value[:KNOWLEDGE_VALUE_MAX_LENGTH] + "..."
            by_category[cat].append(f"- {k['key']}: {value}")

        # 整形
        lines = ["【学習済みの知識】"]
        category_names = {
            "character": "キャラ設定",
            "rules": "業務ルール",
            "members": "社員情報",
            "other": "その他"
        }
        for cat, items in by_category.items():
            cat_name = category_names.get(cat, cat)
            lines.append(f"\n▼ {cat_name}")
            lines.extend(items)

        return "\n".join(lines)

    # =====================================================
    # 検索機能
    # =====================================================

    def search_phase3_knowledge(self, query: str, user_id: str = "user_default", top_k: int = 5) -> Optional[Dict[str, Any]]:
        """
        Phase 3 ナレッジ検索APIを呼び出し（v10.13.3: ハイブリッド検索対応）

        処理フロー:
        1. キーワード抽出
        2. クエリ拡張（キーワードがある場合）
        3. 拡張クエリでベクトル検索API呼び出し
        4. ハイブリッドスコア計算（キーワード40% + ベクトル60%）
        5. スコア順に並び替えて返却

        Args:
            query: 検索クエリ
            user_id: ユーザーID
            top_k: 取得する結果数

        Returns:
            検索結果のDict（見つからない場合やエラー時はNone）
        """
        # Phase 3が無効化されている場合
        if not self.phase3_config.get("enabled", False):
            print("📚 Phase 3 ナレッジ検索は無効化されています")
            return None

        try:
            api_url = self.phase3_config.get("api_url", "")
            timeout = self.phase3_config.get("timeout", 30)
            organization_id = self.phase3_config.get("organization_id", "org_soulsyncs")
            threshold = self.phase3_config.get("similarity_threshold", 0.5)
            keyword_weight = self.phase3_config.get("keyword_weight", 0.4)
            vector_weight = self.phase3_config.get("vector_weight", 0.6)

            # v10.13.3: キーワード抽出とクエリ拡張
            keywords = self.extract_keywords(query)
            expanded_query = self.expand_query(query, keywords) if keywords else query

            # v10.14.2: keywordsが空の場合はベクトルスコアのみで評価（回帰防止）
            if not keywords:
                keyword_weight = 0.0
                vector_weight = 1.0

            print(f"📚 Phase 3 ハイブリッド検索開始: query='{query}', keywords={keywords}")

            # 多めに取得してリランキング
            fetch_top_k = max(top_k * 4, 20)

            # 同期的にAPIを呼び出し
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    api_url,
                    json={
                        "query": expanded_query,  # 拡張クエリを使用
                        "top_k": fetch_top_k,
                        "include_content": True  # コンテンツ取得（キーワードスコア計算用）
                    },
                    headers={
                        "Content-Type": "application/json",
                        "x-user-id": user_id,
                        "X-Tenant-ID": organization_id
                    }
                )

                # ステータスコードの確認
                if response.status_code != 200:
                    print(f"❌ Phase 3 API エラー: status={response.status_code}")
                    return None

                # レスポンスのパース
                data = response.json()

                # 回答拒否の場合
                if data.get("answer_refused", False):
                    print(f"📚 Phase 3: 回答拒否 - {data.get('refused_reason')}")
                    return None

                results = data.get("results", [])

                if not results:
                    print("📚 Phase 3: 検索結果なし")
                    return None

                # v10.13.3: ハイブリッドスコア計算
                for result in results:
                    vector_score = result.get("score", 0)
                    content = result.get("content", "")

                    # キーワードスコアを計算
                    keyword_score = self.calculate_keyword_score(content, keywords) if keywords else 0

                    # ハイブリッドスコア = キーワード重み × キーワードスコア + ベクトル重み × ベクトルスコア
                    hybrid_score = (keyword_weight * keyword_score) + (vector_weight * vector_score)
                    result["hybrid_score"] = hybrid_score
                    result["keyword_score"] = keyword_score
                    result["vector_score"] = vector_score

                # ハイブリッドスコアで並び替え
                results.sort(key=lambda x: x.get("hybrid_score", 0), reverse=True)

                # 上位結果を取得
                top_results = results[:top_k]

                # しきい値でフィルタ（ハイブリッドスコアで判定）
                filtered_results = [
                    r for r in top_results
                    if r.get("hybrid_score", 0) >= threshold
                ]

                if not filtered_results:
                    print(f"📚 Phase 3: しきい値 {threshold} を超える結果なし")
                    return None

                # 最高スコア
                top_score = filtered_results[0].get("hybrid_score", 0) if filtered_results else 0

                print(f"✅ Phase 3 ハイブリッド検索: {len(filtered_results)}件 (top_hybrid: {top_score:.3f})")

                # デバッグ: 上位3件のスコア内訳
                for i, r in enumerate(filtered_results[:3]):
                    doc_title = r.get("document", {}).get("title", "不明")[:20]
                    print(f"  [{i+1}] {doc_title}... hybrid={r.get('hybrid_score', 0):.3f} "
                          f"(kw={r.get('keyword_score', 0):.2f}, vec={r.get('vector_score', 0):.3f})")

                return {
                    "results": filtered_results,
                    "top_score": top_score,
                    "source": "phase3",
                    "search_log_id": data.get("search_log_id")
                }

        except httpx.TimeoutException:
            print(f"⏱️ Phase 3 API タイムアウト ({self.phase3_config.get('timeout', 30)}秒)")
            return None

        except httpx.RequestError as e:
            print(f"❌ Phase 3 API リクエストエラー: {e}")
            return None

        except Exception as e:
            print(f"❌ Phase 3 API 予期しないエラー: {e}")
            traceback.print_exc()
            return None

    @staticmethod
    def format_phase3_results(results: List[Dict[str, Any]]) -> str:
        """
        Phase 3検索結果をLLMに渡す形式に整形

        Args:
            results: Phase 3検索結果のリスト

        Returns:
            整形されたテキスト
        """
        if not results:
            return ""

        formatted_parts = []

        for i, result in enumerate(results, 1):
            content = result.get("content", "")
            score = result.get("score", 0)

            # ドキュメント情報を取得
            doc = result.get("document", {})
            doc_title = doc.get("title", "不明な文書")
            doc_file_name = doc.get("file_name", "")
            page_number = result.get("page_number")

            # 整形
            part = f"【参考情報 {i}】（類似度: {score:.2f}）\n"
            part += f"出典: {doc_title}"
            if doc_file_name:
                part += f" ({doc_file_name})"
            if page_number:
                part += f" - p.{page_number}"
            part += f"\n---\n{content}\n---"

            formatted_parts.append(part)

        return "\n\n".join(formatted_parts)

    def search_legacy_knowledge(self, query: str) -> Optional[Dict[str, Any]]:
        """
        旧システム（soulkun_knowledge）でナレッジ検索

        Args:
            query: 検索クエリ

        Returns:
            検索結果のDict
        """
        try:
            pool = self.get_pool()
            with pool.connect() as conn:
                # LIKE検索でキーまたは値にマッチするものを取得
                sql = """
                    SELECT category, key, value
                    FROM soulkun_knowledge
                    WHERE organization_id = :org_id
                      AND (key ILIKE :pattern ESCAPE '\\' OR value ILIKE :pattern ESCAPE '\\')
                    ORDER BY
                        CASE
                            WHEN key ILIKE :exact ESCAPE '\\' THEN 1
                            WHEN key ILIKE :pattern ESCAPE '\\' THEN 2
                            ELSE 3
                        END
                    LIMIT 5
                """

                escaped = escape_ilike(query)
                pattern = f"%{escaped}%"
                exact = escaped

                result = conn.execute(
                    sqlalchemy.text(sql),
                    {"org_id": self.organization_id, "pattern": pattern, "exact": exact}
                )
                rows = result.fetchall()

                if not rows:
                    return None

                # 信頼度の計算
                first_row = rows[0]
                key_lower = first_row[1].lower()
                query_lower = query.lower()

                if query_lower == key_lower:
                    confidence = 1.0  # 完全一致
                elif query_lower in key_lower:
                    confidence = 0.9  # 部分一致（キーに含まれる）
                elif key_lower in query_lower:
                    confidence = 0.8  # 部分一致（クエリに含まれる）
                else:
                    confidence = 0.6  # それ以外

                # 整形
                formatted_parts = []
                results = []

                for i, row in enumerate(rows, 1):
                    category, key, value = row[0], row[1], row[2]
                    formatted_parts.append(
                        f"【参考情報 {i}】\n"
                        f"項目: {key}\n"
                        f"内容: {value}\n"
                    )
                    results.append({
                        "category": category,
                        "key": key,
                        "value": value
                    })

                return {
                    "source": "legacy",
                    "formatted_context": "\n".join(formatted_parts),
                    "confidence": confidence,
                    "results": results
                }

        except Exception as e:
            print(f"❌ 旧ナレッジ検索エラー: {e}")
            traceback.print_exc()
            return None

    def integrated_knowledge_search(self, query: str, user_id: str = "user_default") -> Dict[str, Any]:
        """
        統合ナレッジ検索（旧システム + Phase 3）

        フォールバック戦略:
        1. 旧システム（soulkun_knowledge）で検索
        2. 高信頼度（80%以上）の結果があれば使用
        3. なければPhase 3（Pinecone）で検索
        4. 類似度70%以上の結果があれば使用
        5. なければ旧システムの低信頼度結果を使用
        6. それでもなければ「学習していない」と返答

        Args:
            query: 検索クエリ
            user_id: ユーザーID

        Returns:
            検索結果のDict
        """
        print(f"🔍 統合ナレッジ検索開始: '{query}'")

        # ステップ1: 旧システムで検索
        legacy_result = self.search_legacy_knowledge(query)

        if legacy_result and legacy_result["confidence"] >= 0.8:
            print(f"📖 旧システム高信頼度結果を使用 (confidence: {legacy_result['confidence']:.2f})")
            return legacy_result

        # ステップ2: Phase 3で検索
        phase3_result = self.search_phase3_knowledge(query, user_id, top_k=5)

        if phase3_result and phase3_result["top_score"] >= self.phase3_config.get("similarity_threshold", 0.5):
            formatted = self.format_phase3_results(phase3_result["results"])
            print(f"🚀 Phase 3結果を使用 (top_score: {phase3_result['top_score']:.3f})")
            return {
                "source": "phase3",
                "formatted_context": formatted,
                "confidence": phase3_result["top_score"],
                "results": phase3_result["results"],
                "search_log_id": phase3_result.get("search_log_id")
            }

        # ステップ3: 旧システムの低信頼度結果を使用
        if legacy_result:
            print(f"📖 旧システム低信頼度結果をフォールバック使用 (confidence: {legacy_result['confidence']:.2f})")
            return legacy_result

        # ステップ4: 結果なし
        print("❌ 統合ナレッジ検索: 関連情報なし")
        return {
            "source": "none",
            "formatted_context": "",
            "confidence": 0.0,
            "results": []
        }

    # =====================================================
    # ハンドラー関数
    # =====================================================

    def handle_learn_knowledge(self, params: Dict, room_id: str, account_id: str,
                               sender_name: str) -> str:
        """
        知識を学習するハンドラー
        - 管理者（カズさん）からは即時反映
        - 他のスタッフからは提案として受け付け、管理部に報告
        v6.9.1: 通知失敗時のメッセージを事実ベースに改善

        Args:
            params: パラメータ {"category": str, "key": str, "value": str}
            room_id: ルームID
            account_id: アカウントID
            sender_name: 送信者名
            context: コンテキスト情報

        Returns:
            レスポンスメッセージ
        """
        category = params.get("category", "other")
        key = params.get("key", "")
        value = params.get("value", "")

        if not key or not value:
            return "🤔 何を覚えればいいかわからなかったウル... もう少し具体的に教えてウル！🐺"

        # テーブル存在確認
        try:
            self.ensure_knowledge_tables()
        except Exception as e:
            print(f"⚠️ 知識テーブル確認エラー: {e}")

        # 管理者判定
        if self.is_admin_func and self.is_admin_func(account_id):
            # 即時保存
            if self.save_knowledge(category, key, value, str(account_id)):
                category_names = {
                    "character": "キャラ設定",
                    "rules": "業務ルール",
                    "other": "その他"
                }
                cat_name = category_names.get(category, category)
                return f"覚えたウル！🐺✨\n\n📝 **{cat_name}**\n・{key}: {value}\n\nこれからはこの知識を活かして返答するウル！"
            else:
                return "😢 覚えようとしたけどエラーが起きたウル... もう一度試してほしいウル！"
        else:
            # スタッフからの提案 → 管理部に報告
            proposal_id = None
            if self.create_proposal_func:
                proposal_id = self.create_proposal_func(
                    proposed_by_account_id=str(account_id),
                    proposed_by_name=sender_name,
                    proposed_in_room_id=str(room_id),
                    category=category,
                    key=key,
                    value=value
                )

            if proposal_id:
                # 管理部に報告
                notified = False
                if self.report_proposal_to_admin_func:
                    try:
                        notified = self.report_proposal_to_admin_func(proposal_id, sender_name, key, value)
                    except Exception as e:
                        print(f"⚠️ 管理部への報告エラー: {e}")

                # v6.9.1: 通知成功/失敗に応じたメッセージ
                # v10.25.0: 「菊地さんに確認」→「ソウルくんが確認」に変更（心理的安全性向上）
                if notified:
                    return f"教えてくれてありがとウル！🐺\n\n提案ID: {proposal_id}\nソウルくんが会社として問題ないか確認するウル！\n確認できたら覚えるウル！✨"
                else:
                    return f"教えてくれてありがとウル！🐺\n\n提案ID: {proposal_id}\n記録はしたウル！\nソウルくんが確認中だから、少し待っててほしいウル！"
            else:
                return "😢 提案を記録しようとしたけどエラーが起きたウル..."

    def handle_forget_knowledge(self, params: Dict, room_id: str, account_id: str,
                                sender_name: str) -> str:
        """
        知識を削除するハンドラー
        - 管理者のみ実行可能

        Args:
            params: パラメータ {"key": str, "category": str}
            room_id: ルームID
            account_id: アカウントID
            sender_name: 送信者名
            context: コンテキスト情報

        Returns:
            レスポンスメッセージ
        """
        key = params.get("key", "")
        category = params.get("category")

        if not key:
            return "🤔 何を忘れればいいかわからなかったウル..."

        # 管理者判定
        if self.is_admin_func and not self.is_admin_func(account_id):
            admin_id = self.admin_account_id or "管理者"
            return f"🙏 知識の削除は菊地さんだけができるウル！\n[To:{admin_id}] {sender_name}さんが「{key}」の設定を削除したいみたいウル！"

        # 削除実行
        if self.delete_knowledge(category, key):
            return f"忘れたウル！🐺\n\n🗑️ 「{key}」の設定を削除したウル！"
        else:
            return f"🤔 「{key}」という設定は見つからなかったウル..."

    def handle_list_knowledge(self, params: Dict, room_id: str, account_id: str,
                              sender_name: str) -> str:
        """
        学習した知識の一覧を表示するハンドラー

        Args:
            params: パラメータ（未使用）
            room_id: ルームID
            account_id: アカウントID
            sender_name: 送信者名
            context: コンテキスト情報

        Returns:
            レスポンスメッセージ
        """
        # テーブル存在確認
        try:
            self.ensure_knowledge_tables()
        except Exception as e:
            print(f"⚠️ 知識テーブル確認エラー: {e}")

        knowledge_list = self.get_all_knowledge()

        if not knowledge_list:
            return "まだ何も覚えてないウル！🐺\n\n「設定：〇〇は△△」と教えてくれたら覚えるウル！"

        # カテゴリごとにグループ化
        by_category = {}
        for k in knowledge_list:
            cat = k["category"]
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(f"・{k['key']}: {k['value']}")

        # 整形
        category_names = {
            "character": "🐺 キャラ設定",
            "rules": "📋 業務ルール",
            "members": "👥 社員情報",
            "other": "📝 その他"
        }

        lines = ["**覚えていること**ウル！🐺✨\n"]
        for cat, items in by_category.items():
            cat_name = category_names.get(cat, f"📁 {cat}")
            lines.append(f"\n**{cat_name}**")
            lines.extend(items)

        lines.append(f"\n\n合計 {len(knowledge_list)} 件覚えてるウル！")

        return "\n".join(lines)

    def handle_query_company_knowledge(self, params: Dict, room_id: str, account_id: str,
                                        sender_name: str) -> Union[str, Dict[str, Any]]:
        """
        会社知識の参照ハンドラー（Phase 3統合版）

        統合ナレッジ検索を使用して、就業規則・マニュアル等から回答を生成する。
        旧システム（soulkun_knowledge）とPhase 3（Pinecone）を自動的に切り替え。

        Args:
            params: {"query": "検索したい内容"}
            room_id: ChatWorkルームID
            account_id: ユーザーのアカウントID
            sender_name: 送信者名
            context: コンテキスト情報

        Returns:
            回答テキスト
        """
        query = params.get("query", "")

        if not query:
            return "🐺 何を調べればいいか教えてほしいウル！\n例：「有給休暇は何日？」「経費精算のルールは？」"

        # v10.22.6: MVV質問の場合は直接回答（ナレッジ検索をバイパス）
        if self.is_mvv_question_func and self.is_mvv_question_func(query):
            print(f"📖 MVV質問検出（会社知識ハンドラー）: user={sender_name}")
            if self.get_full_mvv_info_func:
                mvv_info = self.get_full_mvv_info_func()
                return f"""🐺 ソウルシンクスのMVVについて教えるウル！

{mvv_info}

何か質問があれば聞いてほしいウル！✨"""

        print(f"📚 会社知識クエリ: '{query}' (sender: {sender_name})")

        try:
            # 統合ナレッジ検索を実行
            user_id = f"chatwork_{account_id}"
            search_result = self.integrated_knowledge_search(query, user_id)

            source = search_result.get("source", "none")
            confidence = search_result.get("confidence", 0)
            formatted_context = search_result.get("formatted_context", "")

            # 結果なしの場合
            if source == "none":
                return f"""🐺 ごめんウル！「{query}」については、まだ勉強中ウル…

【ヒント】
📁 Google Driveの「ソウルくんナレッジベース」フォルダに資料をアップロードすると、自動で学習するウル！
📝 または、管理者に「設定: {query} = 回答内容」と教えてもらえると覚えるウル！"""

            # Phase 3.5: 検索結果をBrain層に返す（Brain bypass禁止 - CLAUDE.md §1準拠）
            # ハンドラーはデータ取得のみ。回答生成はBrain（LLM Brain）が担当。
            results_for_brain = search_result.get("results", [])
            source_note = ""
            if source == "phase3" and results_for_brain:
                doc = results_for_brain[0].get("document", {})
                doc_title = doc.get("title", "")
                if doc_title:
                    source_note = f"\n\n📄 参考: {doc_title}"

            return {
                "needs_answer_synthesis": True,
                "status": "found",
                "query": query,
                "source": source,
                "confidence": confidence,
                "formatted_context": formatted_context,
                "results": results_for_brain,
                "source_note": source_note,
                "message": f"🐺 「{query}」について調べたウル！",
            }

        except Exception as e:
            print(f"❌ 会社知識クエリエラー: {e}")
            traceback.print_exc()
            return "🐺 システムエラーが発生したウル…しばらく待ってから再度お試しくださいウル！"

    def handle_local_learn_knowledge(self, key: str, value: str, account_id: str,
                                      sender_name: str, room_id: str) -> str:
        """
        ローカルコマンドによる知識学習（v6.9.1追加）
        「設定：キー=値」形式で呼ばれる

        Args:
            key: キー
            value: 値
            account_id: アカウントID
            sender_name: 送信者名
            room_id: ルームID

        Returns:
            レスポンスメッセージ
        """
        # テーブル存在確認
        try:
            self.ensure_knowledge_tables()
        except Exception as e:
            print(f"⚠️ 知識テーブル確認エラー: {e}")

        # カテゴリを推測（シンプルなルール）
        category = "other"
        key_lower = key.lower()
        if any(w in key_lower for w in ["キャラ", "性格", "モチーフ", "口調", "名前"]):
            category = "character"
        elif any(w in key_lower for w in ["ルール", "業務", "タスク", "期限"]):
            category = "rules"
        elif any(w in key_lower for w in ["社員", "メンバー", "担当"]):
            category = "members"

        # 管理者判定
        if self.is_admin_func and self.is_admin_func(account_id):
            if self.save_knowledge(category, key, value, str(account_id)):
                category_names = {
                    "character": "キャラ設定",
                    "rules": "業務ルール",
                    "members": "社員情報",
                    "other": "その他"
                }
                cat_name = category_names.get(category, category)
                return f"覚えたウル！🐺✨\n\n📝 **{cat_name}**\n・{key}: {value}"
            else:
                return "😢 覚えようとしたけどエラーが起きたウル..."
        else:
            # スタッフからの提案
            proposal_id = None
            if self.create_proposal_func:
                proposal_id = self.create_proposal_func(
                    proposed_by_account_id=str(account_id),
                    proposed_by_name=sender_name,
                    proposed_in_room_id=str(room_id),
                    category=category,
                    key=key,
                    value=value
                )

            if proposal_id:
                notified = False
                if self.report_proposal_to_admin_func:
                    try:
                        notified = self.report_proposal_to_admin_func(proposal_id, sender_name, key, value)
                    except Exception as e:
                        print(f"⚠️ 管理部への報告エラー: {e}")

                # v10.25.0: 「菊地さんに確認」→「ソウルくんが確認」に変更（心理的安全性向上）
                if notified:
                    return f"教えてくれてありがとウル！🐺\n\n提案ID: {proposal_id}\nソウルくんが会社として問題ないか確認するウル！"
                else:
                    return f"教えてくれてありがとウル！🐺\n\n提案ID: {proposal_id}\n記録はしたウル！ソウルくんが確認中だから、少し待っててほしいウル！"
            else:
                return "😢 提案を記録しようとしたけどエラーが起きたウル..."
