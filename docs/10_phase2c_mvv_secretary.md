# Phase 2C: MVV・アチーブ連携 + ベテラン秘書機能拡張

**作成日**: 2026年1月24日
**バージョン**: v1.1
**ステータス**: 📋 承認待ち
**関連**: [11_organizational_theory_guidelines.md](11_organizational_theory_guidelines.md)（組織論的行動指針）

---

## 1. 概要

### 1.1 目的

ソウルくんを「聞かれたら答えるAI」から「**自ら気づいて提案するベテラン秘書**」へ進化させる。

### 1.2 設計原則との整合性

| 原則 | 整合性 | 説明 |
|------|--------|------|
| **脳みそ先行** | ✅ 完全合致 | MVV（価値観）= 判断軸を先に実装 |
| **社内工数削減優先** | ✅ 完全合致 | 日報・週報自動生成で社内工数削減 |
| **MVP先行** | ✅ 完全合致 | 既存機能（B1サマリー）を活用 |
| **参照＋根拠提示** | ✅ 完全合致 | MVVを引用して提案 |

### 1.3 ミッションとの繋がり

> 「人でなくてもできることは全部テクノロジーに任せ、人にしかできないことに人が集中できる状態を作る」

- **MVV連携**: 会社の価値観を理解し、社員の行動とMVVを自然に繋げる
- **日報・週報自動生成**: 報告作業をテクノロジーに任せ、本業に集中

---

## 2. Phase 2C-1: MVV・アチーブ連携（1週間）

### 2.1 現状と課題

| 機能 | 現状 | 課題 |
|------|------|------|
| 目標設定 | WHY→WHAT→HOWフロー ✅実装済み | MVVとの繋がりが明示されない |
| MVV検索 | 「会社の理念は？」で回答 ✅実装済み | 聞かれないと答えない |
| 普段の会話 | タスク・雑談に対応 | MVVを自然に織り込めない |

### 2.2 実装内容

#### A. MVVコンテキスト自動取得

**新規ファイル**: `lib/mvv_context.py`

```python
"""
MVVコンテキスト取得モジュール

組織のMission/Vision/Valuesを取得し、
AI応答に自然に織り込むためのコンテキストを生成する
"""

from typing import Optional, Dict, List
from lib.db import get_db_pool
from sqlalchemy import text

class MVVContext:
    """MVVコンテキスト管理クラス"""

    def __init__(self, organization_id: str):
        self.organization_id = organization_id
        self._cache: Optional[Dict] = None

    async def get_organization_mvv(self) -> Dict:
        """組織のMVV情報を取得"""
        if self._cache:
            return self._cache

        pool = get_db_pool()
        with pool.connect() as conn:
            # Pineconeからナレッジ検索（category='A'=理念・哲学）
            result = conn.execute(text("""
                SELECT content, metadata
                FROM document_chunks
                WHERE organization_id = :org_id
                  AND metadata->>'category' = 'A'
                ORDER BY created_at DESC
                LIMIT 10
            """), {"org_id": self.organization_id})

            chunks = result.fetchall()

        self._cache = self._parse_mvv_chunks(chunks)
        return self._cache

    def _parse_mvv_chunks(self, chunks) -> Dict:
        """チャンクからMVV情報を抽出"""
        return {
            "mission": self._extract_mission(chunks),
            "vision": self._extract_vision(chunks),
            "values": self._extract_values(chunks),
            "action_guidelines": self._extract_guidelines(chunks)
        }

    def get_context_for_prompt(self) -> str:
        """システムプロンプト用のMVVコンテキストを生成"""
        mvv = self._cache or {}

        return f"""
【会社の価値観】
ミッション: {mvv.get('mission', '未設定')}
ビジョン: {mvv.get('vision', '未設定')}

💡 応答のヒント:
- ユーザーの行動がMVVにどう繋がるか、自然に伝える
- 困っている時は会社の価値観を思い出させて励ます
- 押し付けがましくなく、さりげなく織り込む
- 「〜というミッションに繋がりますね」のような直接的な表現は避ける
"""
```

#### B. システムプロンプト拡張

**変更ファイル**: `chatwork-webhook/main.py` - `get_ai_response()`関数

```python
# 現在のプロンプトに追加
async def get_ai_response(message, user_info, room_id, ...):
    # MVVコンテキストを取得
    mvv_context = MVVContext(user_info.get('organization_id'))
    mvv_prompt = await mvv_context.get_context_for_prompt()

    system_prompt = f"""
{existing_prompt}

{mvv_prompt}
"""
```

#### C. 選択理論「4つの基本欲求」分析

**変更ファイル**: `lib/goal_setting.py`

```python
# 選択理論に基づく4つの基本欲求（+楽しさ）
FOUR_BASIC_NEEDS = {
    "survival": {
        "name": "安定・安心",
        "keywords": ["安定", "給料", "雇用", "健康", "安全"],
        "description": "生存欲求：経済的・身体的な安全を求める"
    },
    "love": {
        "name": "つながり・チーム",
        "keywords": ["仲間", "チーム", "認められ", "感謝", "一緒に"],
        "description": "愛・所属欲求：人との繋がりを求める"
    },
    "power": {
        "name": "成長・達成感",
        "keywords": ["成長", "達成", "スキル", "評価", "昇進", "貢献"],
        "description": "力の欲求：達成感や承認を求める"
    },
    "freedom": {
        "name": "自律・自分で決める",
        "keywords": ["自由", "自分で", "選択", "裁量", "主体的"],
        "description": "自由欲求：自己決定を求める"
    },
    "fun": {
        "name": "やりがい・楽しさ",
        "keywords": ["楽しい", "面白い", "やりがい", "ワクワク", "好き"],
        "description": "楽しみ欲求：興味や喜びを求める"
    }
}

class NeedAnalyzer:
    """ユーザーの欲求傾向を分析"""

    def analyze_from_goals(self, past_goals: List[Dict]) -> Dict[str, float]:
        """過去の目標から欲求傾向を分析"""
        need_scores = {need: 0.0 for need in FOUR_BASIC_NEEDS}

        for goal in past_goals:
            why_text = goal.get('why_answer', '')
            for need_key, need_info in FOUR_BASIC_NEEDS.items():
                for keyword in need_info['keywords']:
                    if keyword in why_text:
                        need_scores[need_key] += 1.0

        # 正規化
        total = sum(need_scores.values()) or 1
        return {k: v/total for k, v in need_scores.items()}

    def get_motivation_hints(self, need_scores: Dict[str, float]) -> str:
        """欲求傾向に基づくモチベーションヒントを生成"""
        dominant_needs = sorted(need_scores.items(), key=lambda x: -x[1])[:2]

        hints = []
        for need_key, score in dominant_needs:
            if score > 0.2:
                need_info = FOUR_BASIC_NEEDS[need_key]
                hints.append(f"- {need_info['name']}を重視する傾向があります")

        return "\n".join(hints)
```

### 2.3 実装工数

| タスク | 工数 | 担当 |
|--------|------|------|
| MVVコンテキスト取得（lib/mvv_context.py） | 4時間 | エンジニア |
| プロンプト拡張（main.py） | 4時間 | エンジニア |
| 4つの基本欲求分析 | 8時間 | エンジニア |
| テスト・調整 | 8時間 | エンジニア |
| **合計** | **24時間（3日）** | |

### 2.4 完了定義

| # | 要件 | 確認方法 |
|---|------|----------|
| 1 | MVVコンテキストがプロンプトに含まれる | ログ確認 |
| 2 | 「やる気が出ない」→ MVVに絡めた励ましが返る | 手動テスト |
| 3 | 目標設定時にWHY→MVVの繋がりを確認できる | 手動テスト |
| 4 | 押し付けがましくない自然な織り込み | ユーザーフィードバック |

---

## 3. Phase 2C-2: 日報・週報自動生成（1週間）

### 3.1 概要

既存のB1サマリー機能を活用し、日報・週報を自動生成する。
（Phase 1-C「レポート自動生成」の前倒し実装）

### 3.2 実装内容

#### A. 日報テンプレート生成

**新規ファイル**: `lib/report_generator.py`

```python
"""
日報・週報自動生成モジュール

B1サマリーとタスク完了履歴を集約し、
報告書を自動生成する
"""

class DailyReportGenerator:
    """日報自動生成"""

    async def generate(self, user_id: str, date: datetime) -> str:
        """日報を生成"""
        # B1サマリーから当日の会話を取得
        summaries = await self._get_daily_summaries(user_id, date)

        # 完了タスクを取得
        completed_tasks = await self._get_completed_tasks(user_id, date)

        # 日報テンプレートに適用
        return self._apply_template(summaries, completed_tasks)

    def _apply_template(self, summaries, tasks) -> str:
        return f"""
📋 **日報** ({date.strftime('%Y/%m/%d')})

## 本日の成果
{self._format_completed_tasks(tasks)}

## 進行中の案件
{self._format_in_progress(summaries)}

## 明日の予定
{self._format_tomorrow_plan(summaries)}

## 所感・気づき
{self._extract_insights(summaries)}
"""

class WeeklyReportGenerator:
    """週報自動生成"""

    async def generate(self, user_id: str, week_start: datetime) -> str:
        """週報を生成"""
        # 1週間分の日報を集約
        daily_reports = []
        for i in range(7):
            day = week_start + timedelta(days=i)
            daily = await DailyReportGenerator().generate(user_id, day)
            daily_reports.append(daily)

        # 週次サマリーを生成（LLMで要約）
        return await self._summarize_week(daily_reports)
```

#### B. 自動配信設定

**Cloud Scheduler設定**:

| ジョブ名 | スケジュール | 内容 |
|----------|--------------|------|
| daily-report-generation | 毎日 18:00 JST | 日報下書き生成・本人に送信 |
| weekly-report-generation | 毎週金曜 17:00 JST | 週報下書き生成・本人に送信 |

### 3.3 実装工数

| タスク | 工数 | 担当 |
|--------|------|------|
| 日報生成ロジック | 8時間 | エンジニア |
| 週報生成ロジック | 8時間 | エンジニア |
| Cloud Scheduler設定 | 2時間 | エンジニア |
| テスト・調整 | 6時間 | エンジニア |
| **合計** | **24時間（3日）** | |

### 3.4 完了定義

| # | 要件 | 確認方法 |
|---|------|----------|
| 1 | 日報が毎日18:00に自動生成される | Scheduler実行ログ |
| 2 | 週報が毎週金曜17:00に自動生成される | Scheduler実行ログ |
| 3 | B1サマリーの内容が反映されている | 内容確認 |
| 4 | タスク完了履歴が含まれている | 内容確認 |

---

## 4. 追加機能ロードマップ（Phase 2C以降）

### 4.1 優先度マトリックス

| 優先度 | 機能 | 実装時期 | 依存関係 |
|--------|------|----------|----------|
| ⭐⭐⭐⭐⭐ | MVV・アチーブ連携 | **Phase 2C-1**（今すぐ） | なし |
| ⭐⭐⭐⭐⭐ | 日報・週報自動生成 | **Phase 2C-2**（今すぐ） | B1サマリー |
| ⭐⭐⭐⭐ | 会議前準備 | **Phase C完了後** | Phase C（議事録） |
| ⭐⭐⭐⭐ | 提案書テンプレート | **Phase 3拡張** | Phase 3（ナレッジ） |
| ⭐⭐⭐ | チーム能力分析 | **Q2** | A1-A4データ蓄積 |
| ⭐⭐ | スケジュール連携 | **Phase 4A以降** | Flask→FastAPI移行 |
| ⭐⭐ | 顧客フォローアップ | **CRM導入後** | CRMシステム |
| ⭐ | メール連携 | **2027年** | 複雑度高、プライバシー設計 |
| ⭐ | リソース予測 | **2027年以降** | 歴史データ蓄積、ML |

### 4.2 実装順序の根拠

```
【脳みそ先行原則に従った順序】

Phase 2C-1: MVV連携（判断軸=脳みそ）
    ↓
Phase 2C-2: 日報・週報（既存機能活用=MVP先行）
    ↓
Phase C: 議事録自動化（ロードマップ通り、Q3）
    ↓
Phase C+: 会議前準備（Phase Cの拡張）
    ↓
Phase 3拡張: 提案書テンプレート（ナレッジカテゴリD）
    ↓
Phase 4A: テナント分離
    ↓
外部API連携（Calendar, Gmail等）
```

### 4.3 延期理由の詳細

| 機能 | 延期理由 | 推奨時期 |
|------|----------|----------|
| スケジュール連携 | Flask→FastAPI移行完了後に外部API連携を設計すべき。現在のハイブリッドアーキテクチャでは複雑度が高い | Phase 4A以降（2026 Q4） |
| メール連携 | Gmail APIはプライバシー設計が必要。OAuth同意画面の審査も必要 | 2027年 |
| リソース予測 | 歴史データが1年分蓄積されてからMLモデルを構築すべき | 2027年以降 |
| 顧客フォローアップ | CRMシステムの導入状況が不明。CRM連携の前提条件を確認後 | CRM導入後 |

---

## 5. 技術設計

### 5.1 変更対象ファイル

| ファイル | 変更内容 | 新規/変更 |
|----------|----------|----------|
| `lib/mvv_context.py` | MVVコンテキスト取得 | 新規 |
| `lib/need_analyzer.py` | 4つの基本欲求分析 | 新規 |
| `lib/report_generator.py` | 日報・週報生成 | 新規 |
| `chatwork-webhook/main.py` | プロンプト拡張 | 変更 |
| `lib/goal_setting.py` | 欲求分析統合 | 変更 |
| `lib/memory/goal_integration.py` | MVV連携追加 | 変更 |

### 5.2 DBテーブル

既存テーブルを活用（新規テーブルなし）:
- `document_chunks`: MVV情報取得（category='A'）
- `conversation_summaries`: B1サマリー
- `chatwork_tasks`: タスク完了履歴

### 5.3 外部依存

| 依存 | 説明 | リスク |
|------|------|--------|
| OpenAI API | プロンプト拡張による追加コスト | 低（微増） |
| Pinecone | MVV検索 | 低（既存利用） |

---

## 6. リスクと軽減策

| リスク | 影響度 | 軽減策 |
|--------|--------|--------|
| MVVが押し付けがましくなる | 中 | プロンプト調整、ユーザーフィードバック収集 |
| 日報の品質が低い | 中 | テンプレート改善、LLM要約品質向上 |
| B1サマリーのデータ不足 | 低 | 10件以上の会話でのみ生成 |

---

## 7. 成功基準

### Phase 2C-1（MVV連携）

- [ ] 「やる気が出ない」→ MVVに絡めた励ましが返る
- [ ] 目標設定時にWHY→MVVの繋がりを確認できる
- [ ] 押し付けがましくない自然な織り込み

### Phase 2C-2（日報・週報）

- [ ] 日報が毎日18:00に自動生成される
- [ ] 週報が毎週金曜17:00に自動生成される
- [ ] ユーザーが「役に立った」と評価

---

## 8. 次のアクション

### 承認後の実装順序

1. **Week 1（Phase 2C-1）**
   - Day 1-2: lib/mvv_context.py 新規作成
   - Day 3: get_ai_response() プロンプト拡張
   - Day 4-5: 4つの基本欲求分析追加、テスト

2. **Week 2（Phase 2C-2）**
   - Day 1-2: lib/report_generator.py 日報生成
   - Day 3: 週報生成ロジック
   - Day 4: Cloud Scheduler設定
   - Day 5: 本番デプロイ、動作確認

---

## 改訂履歴

| バージョン | 日付 | 変更内容 |
|-----------|------|---------|
| v1.0 | 2026-01-24 | 初版作成（Claude Code） |
| v1.1 | 2026-01-24 | 組織論的行動指針（11_organizational_theory_guidelines.md）との連携追加 |

---

**[📁 目次に戻る](00_README.md)**
