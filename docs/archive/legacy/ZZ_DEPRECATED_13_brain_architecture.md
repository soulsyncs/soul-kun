> ⚠️ **DEPRECATED - 参照禁止**
>
> このファイルは **`docs/25_llm_native_brain_architecture.md`** に統合されました。
>
> | 統合先 | 25章 第5-6章「アーキテクチャ・各層の詳細設計」 |
> |--------|------------------------------------------|
> | 理由 | キーワードマッチ方式からLLM常駐型への移行 |
> | 日付 | 2026-01-30 |
>
> **👉 参照すべきファイル:** [25章 LLM常駐型脳アーキテクチャ](../25_llm_native_brain_architecture.md)

---

# 第13章：ソウルくんの脳アーキテクチャ設計書

**バージョン:** v1.0.0
**作成日:** 2026-01-26
**作成者:** Claude Code（経営参謀・SE・PM）
**ステータス:** 設計確定

---

## 目次

1. [エグゼクティブサマリー](#1-エグゼクティブサマリー)
2. [カズさんのビジョン](#2-カズさんのビジョン)
3. [設計原則（7つの鉄則）](#3-設計原則7つの鉄則)
4. [アーキテクチャ全体像](#4-アーキテクチャ全体像)
5. [記憶層（Memory Layer）](#5-記憶層memory-layer)
6. [理解層（Understanding Layer）](#6-理解層understanding-layer)
7. [判断層（Decision Layer）](#7-判断層decision-layer)
8. [実行層（Execution Layer）](#8-実行層execution-layer)
9. [状態管理層（State Management Layer）](#9-状態管理層state-management-layer)
10. [データベース設計](#10-データベース設計)
11. [API設計](#11-api設計)
12. [移行計画](#12-移行計画)
13. [テスト戦略](#13-テスト戦略)
14. [リスクと対策](#14-リスクと対策)
15. [実装チェックリスト](#15-実装チェックリスト)
16. [付録](#16-付録)

---

## 1. エグゼクティブサマリー

### 1.1 この設計書の目的

**ソウルくんの「脳」を設計し、人間の秘書のように「あうんの呼吸」で働けるAIアーキテクチャを実現する。**

### 1.2 3行で要約

1. **何をするか**: 全ての入力をまず「脳」が受け取り、記憶を参照し、意図を理解し、適切な機能に指令を出す
2. **なぜ必要か**: 現状はバイパスルートが存在し、機能ごとに独立して動作しているため、人間の秘書のような一貫した対応ができない
3. **どう作るか**: 4層構造（記憶→理解→判断→実行）＋状態管理を統一し、全ての入力が「脳」を通る設計に変更する

### 1.3 この設計書の位置づけ

```
設計書体系
├─ 01_philosophy_and_principles.md  ← 哲学・原則（なぜ作るか）
├─ 02_phase_overview.md             ← Phase構成（いつ作るか）
├─ 03_database_design.md            ← DB設計（何を保存するか）
├─ 10_phase2_b_memory_framework.md  ← 記憶機能（覚える能力）
├─ 10_phase2c_mvv_secretary.md      ← MVV・秘書機能（判断軸）
└─ ★ 13_brain_architecture.md       ← 【本設計書】脳の全体設計
```

### 1.4 関連する既存Phase

| Phase | 名称 | 本設計書との関係 |
|-------|------|-----------------|
| Phase 2 | AI応答・評価機能 | 脳の基盤（ai_commander）が存在 |
| Phase 2 A1-A4 | 気づく能力 | 脳が参照するインサイト情報 |
| Phase 2 B | 覚える能力 | 脳の記憶層として統合 |
| Phase 2.5 | 目標達成支援 | 脳が管理する対話フロー |
| Phase 2C | MVV・秘書機能 | 脳の判断軸（価値観）|
| Phase X | アナウンス機能 | 脳が指令を出す実行機能 |

---

## 2. カズさんのビジョン

### 2.1 カズさんの言葉（原文）

> 「ソウルくんにお願いしたら、まず人間の秘書がやってくれるかのような理解の仕方とか、記憶をしてほしいんですよね。」

> 「そのためには、記憶もすべてそのAIの司令塔にちゃんと紐づいていてほしいですし、どの記憶もすべてを常に窓口として、俺たちはどういうことを望んでいるのかを汲み取って、まるでできる秘書っていうのはあうんの呼吸のように一緒に仕事をして、求めてることを手に取るように分かる状態になってほしいんです。」

> 「絶対にAIの司令塔というか、ソウルくんの脳みそ的な役割が、僕らの言ってることを汲み取って、各システムに司令を出すっていう順序だけは、絶対変えたくないんです。」

### 2.2 ビジョンの解釈

| カズさんの言葉 | 技術的な解釈 |
|--------------|-------------|
| 「人間の秘書のような理解」 | 曖昧な入力を文脈から補完して理解する |
| 「記憶が脳に紐づいている」 | 全ての記憶を統一的に参照できる設計 |
| 「あうんの呼吸」 | 過去の対話パターンから先読みする |
| 「手に取るように分かる」 | 意図の推論 + 確認モードで精度を担保 |
| 「脳みそが司令を出す順序」 | 全入力 → 脳 → 各機能 の順序を絶対に守る |

### 2.3 目指すべき「できる秘書」の特徴

| 特徴 | 人間の秘書なら | ソウルくんでは |
|------|--------------|---------------|
| **聞く力** | 雑な指示も意図を汲み取る | 曖昧表現の解析、省略の補完 |
| **覚える力** | 過去の依頼や好みを覚えている | Memory Framework統合 |
| **確認する力** | 分からなければ聞き返す | 確認モード（confidence < 0.7で発動）|
| **判断する力** | 適切な手段を選ぶ | SYSTEM_CAPABILITIESからの動的選択 |
| **先読みする力** | 次に必要なことを予測する | 関連アクションの提案 |
| **報告する力** | 結果を適切に伝える | 統一されたレスポンス形式 |

---

## 3. 設計原則（7つの鉄則）

### 3.1 脳アーキテクチャの7つの鉄則

これらの原則は**絶対に変えてはならない**。将来の機能拡張時も、この原則に従うこと。

| # | 鉄則 | 説明 | 違反した場合のリスク |
|---|------|------|-------------------|
| 1 | **全ての入力は脳を通る** | 例外なし。バイパスルート禁止 | 機能ごとに異なる応答、一貫性の欠如 |
| 2 | **脳は全ての記憶にアクセスできる** | 会話、人物、ナレッジ、タスク、嗜好 | 文脈を失った対応、「初めまして」の繰り返し |
| 3 | **脳が判断し、機能は実行するだけ** | 機能に判断ロジックを持たせない | 責務の混在、保守性の低下 |
| 4 | **機能拡張しても脳の構造は変わらない** | カタログへの追加のみで対応 | 脳のコード肥大化、技術的負債 |
| 5 | **確認は脳の責務** | 曖昧な場合は脳が確認を判断 | ユーザー体験の断片化 |
| 6 | **状態管理は脳が統一管理** | 各機能が独自に状態を持たない | 状態の不整合、バグの温床 |
| 7 | **速度より正確性を優先** | 遅くても正確な応答を返す | 誤った動作、信頼の失墜 |

### 3.2 CLAUDE.md 10の鉄則との整合性

| CLAUDE.md鉄則 | 本設計での対応 |
|--------------|---------------|
| 1. 全テーブルにorganization_id | ✅ 全記憶テーブルに含む |
| 2. RLS実装 | ✅ 脳が参照する記憶もRLS対象 |
| 3. 監査ログを記録 | ✅ 脳の判断結果を記録 |
| 4. API認証必須 | ✅ 脳へのアクセスも認証必須 |
| 5. ページネーション | ✅ 記憶検索に適用 |
| 6. キャッシュTTL | ✅ 頻繁な記憶はキャッシュ |
| 7. APIバージョニング | ✅ 脳APIもバージョン管理 |
| 8. エラーに機密情報含めない | ✅ 脳の判断理由もサニタイズ |
| 9. SQLパラメータ化 | ✅ 記憶検索クエリもパラメータ化 |
| 10. トランザクション内API禁止 | ✅ 脳の処理も分離 |

---

## 4. アーキテクチャ全体像

### 4.1 現状のアーキテクチャ（問題点）

```
                    ユーザーのメッセージ
                           │
                           ▼
        ┌──────────────────────────────────────────┐
        │           chatwork_webhook()             │
        └──────────────────────────────────────────┘
                           │
        ┌──────────────────┼───────────────────────┐
        │                  │                       │
        ▼                  ▼                       ▼
┌─────────────┐   ┌─────────────┐         ┌─────────────┐
│ 目標設定    │   │ アナウンス  │         │ ローカル    │
│ セッション  │   │ 確認中      │         │ コマンド    │
│ ⛔バイパス  │   │ ⛔バイパス  │         │ ⛔バイパス  │
└─────────────┘   └─────────────┘         └─────────────┘
        │                  │                       │
        │                  │                       │
        │                  ▼                       │
        │         ┌─────────────────┐              │
        │         │  ai_commander() │              │
        │         │  （AI司令塔）   │              │
        │         └─────────────────┘              │
        │                  │                       │
        └──────────────────┼───────────────────────┘
                           ▼
                    各ハンドラー実行
```

**問題点:**
1. 複数のバイパスルートが存在（目標設定、アナウンス、ローカルコマンド）
2. バイパスルートはキーワードマッチで動作し、AIの判断力を活用していない
3. 記憶（Memory Framework）がai_commanderに統合されていない
4. 状態管理が各機能で独立している

### 4.2 目指すアーキテクチャ（理想形）

```
                    ユーザーのメッセージ
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                    ソウルくんの「脳」                            │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                   記憶層（Memory Layer）                 │  │
│  │                                                          │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │  │
│  │  │会話履歴  │ │人物情報  │ │ユーザー  │ │会社知識  │   │  │
│  │  │(B4検索) │ │(persons) │ │嗜好(B2) │ │(Phase3) │   │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │  │
│  │  │会話要約  │ │タスク    │ │目標      │ │インサイト│   │  │
│  │  │(B1)     │ │(tasks)  │ │(goals)  │ │(A1-A4)  │   │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │  │
│  └─────────────────────────────────────────────────────────┘  │
│                            ↓                                   │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                  理解層（Understanding Layer）           │  │
│  │                                                          │  │
│  │  ・意図の推論（何をしたいのか）                          │  │
│  │  ・省略の補完（前の会話から補う）                        │  │
│  │  ・曖昧性の解消（「あれ」→具体的な対象）                │  │
│  │  ・感情の検出（困っている、急いでいる等）               │  │
│  │                                                          │  │
│  └─────────────────────────────────────────────────────────┘  │
│                            ↓                                   │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                   判断層（Decision Layer）               │  │
│  │                                                          │  │
│  │  ・機能選択（SYSTEM_CAPABILITIESから選択）              │  │
│  │  ・確認要否（confidence < 0.7なら確認モード）           │  │
│  │  ・複数アクション判定（1つ？複数？順序は？）            │  │
│  │  ・MVV整合性（会社の価値観に沿っているか）              │  │
│  │                                                          │  │
│  └─────────────────────────────────────────────────────────┘  │
│                            ↓                                   │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                  状態管理層（State Layer）               │  │
│  │                                                          │  │
│  │  ・現在の対話状態（通常/目標設定中/アナウンス確認中）   │  │
│  │  ・マルチステップの進捗（WHY→WHAT→HOW）                 │  │
│  │  ・pending操作（確認待ち、タスク作成待ち等）            │  │
│  │                                                          │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
                    実行指令（Execution Command）
                           │
            ┌──────────────┼──────────────┐
            ↓              ↓              ↓
      ┌──────────┐  ┌──────────┐  ┌──────────┐
      │タスク管理│  │アナウンス│  │ナレッジ  │ ...
      │ハンドラー│  │ハンドラー│  │検索     │
      └──────────┘  └──────────┘  └──────────┘
```

### 4.3 アーキテクチャ比較表

| 観点 | 現状 | 目指す姿 |
|------|------|---------|
| 入力の窓口 | 複数（バイパスあり） | 脳のみ（唯一） |
| 記憶の参照 | 一部のみ（persons, knowledge） | 全て（8種類+） |
| 意図の理解 | キーワードマッチ中心 | AI推論＋文脈補完 |
| 判断の一貫性 | 機能ごとに異なる | 脳で統一 |
| 状態管理 | 機能ごとに独立 | 脳で統一管理 |
| 拡張性 | 機能追加時に分岐が増える | カタログ追加のみ |

---

## 5. 記憶層（Memory Layer）

### 5.1 概要

記憶層は、脳が参照する**全ての記憶を統一的に管理**する層です。

**設計思想:**
- 脳は「何を覚えているか」を知っている
- 全ての記憶は同じインターフェースでアクセスできる
- 記憶の種類が増えても、脳のコードは変わらない

### 5.2 記憶の種類と優先度

| 優先度 | 記憶の種類 | データソース | 参照タイミング | 重要度 |
|--------|-----------|-------------|---------------|--------|
| 1 | **現在の状態** | brain_conversation_states | 常に最初 | ★★★ |
| 2 | **CEO教え** | ceo_teachings (Phase 2D) | 判断・応答生成時 | ★★★ |
| 3 | **直近の会話** | conversation_history (Firestore) | 常に | ★★★ |
| 4 | **会話要約** | conversation_summaries (B1) | 文脈補完時 | ★★☆ |
| 5 | **ユーザー嗜好** | user_preferences (B2) | 応答生成時 | ★★☆ |
| 6 | **人物情報** | persons | 名前解決時 | ★★★ |
| 7 | **タスク情報** | chatwork_tasks | タスク関連時 | ★★☆ |
| 8 | **目標情報** | goals, goal_setting_sessions | 目標関連時 | ★★☆ |
| 9 | **会社知識** | documents, soulkun_knowledge | 質問時 | ★★☆ |
| 10 | **インサイト** | soulkun_insights (A1-A4) | 気づき参照時 | ★☆☆ |
| 11 | **会話検索** | conversation_index (B4) | 過去参照時 | ★☆☆ |

### 5.3 記憶アクセスインターフェース

```python
# lib/brain/memory_access.py

class BrainMemoryAccess:
    """
    脳が記憶にアクセスするための統一インターフェース

    全ての記憶はこのクラスを通じてアクセスする。
    記憶の種類が増えても、このインターフェースは変わらない。
    """

    def __init__(self, pool, org_id: str, user_id: str, room_id: str):
        self.pool = pool
        self.org_id = org_id
        self.user_id = user_id
        self.room_id = room_id

    async def get_full_context(self) -> BrainContext:
        """
        脳が判断に必要な全ての記憶を取得

        Returns:
            BrainContext: 統合されたコンテキスト情報
        """
        return BrainContext(
            current_state=await self._get_current_state(),
            recent_conversation=await self._get_recent_conversation(),
            conversation_summary=await self._get_conversation_summary(),
            user_preferences=await self._get_user_preferences(),
            person_info=await self._get_person_info(),
            recent_tasks=await self._get_recent_tasks(),
            active_goals=await self._get_active_goals(),
            relevant_knowledge=None,  # 必要時に遅延取得
            insights=await self._get_relevant_insights(),
        )

    async def search_memory(
        self,
        query: str,
        memory_types: List[MemoryType] = None
    ) -> List[MemorySearchResult]:
        """
        指定した記憶タイプから検索

        Args:
            query: 検索クエリ
            memory_types: 検索対象の記憶タイプ（Noneなら全て）

        Returns:
            検索結果のリスト
        """
        pass
```

### 5.4 BrainContextデータ構造

```python
# lib/brain/models.py

@dataclass
class BrainContext:
    """脳が参照する統合コンテキスト"""

    # 現在の状態（最優先）
    current_state: Optional[ConversationState]

    # CEO教え（Phase 2D）- 判断の最上位根拠
    ceo_teachings: List[CEOTeachingInfo]             # CEOの教え（優先度2）

    # 会話関連
    recent_conversation: List[ConversationMessage]  # 直近10件
    conversation_summary: Optional[SummaryData]      # 過去の要約

    # ユーザー関連
    user_preferences: Optional[PreferenceData]       # 嗜好
    sender_name: str                                  # 送信者名

    # 人物・タスク関連
    person_info: List[PersonInfo]                    # 記憶している人物
    recent_tasks: List[TaskInfo]                     # 関連タスク

    # 目標関連
    active_goals: List[GoalInfo]                     # アクティブな目標
    goal_session: Optional[GoalSessionInfo]          # 目標設定セッション

    # 知識関連（遅延取得）
    relevant_knowledge: Optional[List[KnowledgeChunk]]

    # インサイト関連
    insights: List[InsightInfo]                      # 気づき情報

    def to_prompt_context(self) -> str:
        """LLMプロンプト用のコンテキスト文字列を生成"""
        pass

    def has_active_session(self) -> bool:
        """マルチステップセッションが進行中か"""
        return self.current_state is not None and self.current_state.is_active
```

### 5.5 記憶の更新タイミング

| 記憶の種類 | 更新タイミング | 更新処理 |
|-----------|--------------|---------|
| 現在の状態 | 状態遷移時 | 脳が直接更新 |
| CEO教え | CEO会話検出時 | CEOLearningLayer.extract_and_save() (Phase 2D) |
| 直近の会話 | 毎メッセージ | save_conversation_history() |
| 会話要約 | 10件超過時 | ConversationSummary.generate_and_save() |
| ユーザー嗜好 | 学習検出時 | UserPreference.learn() |
| 人物情報 | save_memory時 | save_person() |
| タスク情報 | タスク操作時 | sync_chatwork_tasks() |
| 目標情報 | 目標操作時 | GoalSettingSession更新 |
| 会社知識 | ドキュメント更新時 | watch_google_drive() |
| インサイト | 検出時 | pattern-detection Cloud Function |
| 会話検索 | 毎メッセージ | ConversationSearch.index() |
| 会話検索 | 毎メッセージ | ConversationSearch.index() |

---

## 6. 理解層（Understanding Layer）

### 6.1 概要

理解層は、ユーザーの入力から**真の意図を推論**する層です。

**設計思想:**
- 人間は省略する、曖昧に言う、前提を共有していると思っている
- ソウルくんは「秘書」として、その省略・曖昧さを補完する
- 分からない時は推測せず、確認する

### 6.2 理解プロセス

```
入力: 「あれ、どうなった？」
          │
          ▼
┌─────────────────────────────────────┐
│ Step 1: 省略の検出                  │
│ - 「あれ」= 不明な代名詞            │
│ - 「どうなった」= 状態の確認        │
└─────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────┐
│ Step 2: 記憶の参照                  │
│ - 直近の会話から候補を抽出          │
│ - 最近のタスクから候補を抽出        │
│ - 進行中のセッションから候補を抽出  │
└─────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────┐
│ Step 3: 候補のランキング            │
│ 1. 昨日お願いした経費精算タスク     │
│ 2. 先週の採用候補者の件             │
│ 3. 今朝話してた会議室予約           │
└─────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────┐
│ Step 4: 確認要否の判断              │
│ - 候補が1つで確信度高い → 直接回答  │
│ - 候補が複数 or 確信度低い → 確認   │
└─────────────────────────────────────┘
          │
          ▼
出力: 確認モード or 直接処理
```

### 6.3 理解の6つの要素

| 要素 | 説明 | 例 |
|------|------|-----|
| **意図（Intent）** | 何をしたいのか | タスク作成、検索、質問 |
| **対象（Entity）** | 誰/何について | 「崇樹」「経費精算」「有給」 |
| **時間（Time）** | いつのこと | 「明日」「先週の」「さっき」 |
| **緊急度（Urgency）** | どのくらい急ぎ | 「すぐ」「急ぎで」「いつでも」 |
| **感情（Emotion）** | どんな気持ち | 困っている、怒っている、楽しい |
| **文脈（Context）** | 前の会話との繋がり | 「さっきの続き」「あれ」 |

### 6.4 曖昧表現の解決パターン

| パターン | 曖昧表現 | 解決方法 |
|---------|---------|---------|
| **代名詞** | あれ、それ、あの人 | 直近の会話から候補抽出 |
| **省略** | 「完了にして」（何を？） | 直近のタスク/会話から推測 |
| **略称** | 「経精」「採教」 | 会社知識から正式名称を検索 |
| **敬称バリエーション** | 崇樹、崇樹さん、崇樹くん | 人物DBで名寄せ |
| **日付表現** | 明日、来週、月末 | 現在日時から計算 |
| **相対時間** | さっき、この前、最近 | 会話履歴から推測 |

### 6.5 意図推論のLLMプロンプト

```python
UNDERSTANDING_PROMPT = """
あなたは「ソウルくん」の理解層です。
ユーザーの発言から、真の意図を推論してください。

【あなたの仕事】
1. ユーザーが「何をしたいのか」を推論する
2. 省略されている情報を、コンテキストから補完する
3. 曖昧な表現を具体的に解決する
4. 確信度を評価する（0.0〜1.0）

【コンテキスト情報】
{context}

【ユーザーの発言】
{message}

【出力形式】
{
  "intent": "推論した意図",
  "entities": {
    "person": "対象の人物（解決済み）",
    "object": "対象の物事",
    "time": "時間（解決済み、ISO形式）",
    "urgency": "low/medium/high"
  },
  "resolved_ambiguities": [
    {"original": "曖昧表現", "resolved": "解決後", "source": "解決に使った情報源"}
  ],
  "confidence": 0.0-1.0,
  "reasoning": "この推論をした理由",
  "needs_confirmation": true/false,
  "confirmation_options": ["候補1", "候補2"]  // needs_confirmation=trueの場合
}
"""
```

### 6.6 確認モードの発動条件

| 条件 | 閾値 | 動作 |
|------|------|------|
| 確信度が低い | confidence < 0.7 | 確認モード発動 |
| 複数候補がある | candidates >= 2 | 選択肢を提示 |
| 危険な操作 | action in [delete, send_all] | 必ず確認 |
| 重要な金額 | amount > 100,000 | 金額を確認 |
| 複数人への送信 | recipients >= 3 | 宛先を確認 |

---

## 7. 判断層（Decision Layer）

### 7.1 概要

判断層は、理解した意図に基づいて**どの機能を実行するかを決定**する層です。

**設計思想:**
- SYSTEM_CAPABILITIESカタログから機能を動的に選択
- 新機能追加時はカタログに追加するだけで脳が認識
- MVV（ミッション・ビジョン・バリュー）に沿った判断

### 7.2 判断プロセス

```
理解層からの出力（意図・エンティティ・確信度）
          │
          ▼
┌─────────────────────────────────────┐
│ Step 1: 状態チェック                │
│ - マルチステップセッション中？      │
│ - pending操作あり？                 │
│ → あれば、そのフローを継続          │
└─────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────┐
│ Step 2: 機能候補の抽出              │
│ - SYSTEM_CAPABILITIESから候補抽出   │
│ - 意図とのマッチング                │
│ - 各候補にスコアリング              │
└─────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────┐
│ Step 3: 確認要否の判断              │
│ - 確信度 < 0.7 → 確認モード         │
│ - 危険な操作 → 確認モード           │
│ - 確信度 >= 0.9 → 直接実行          │
└─────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────┐
│ Step 4: MVV整合性チェック           │
│ - NGパターン検出                    │
│ - 適切なトーンか                    │
│ - 会社の価値観に沿っているか        │
└─────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────┐
│ Step 5: 実行コマンドの生成          │
│ - アクション名                      │
│ - パラメータ（解決済み）            │
│ - 確信度                            │
│ - 理由                              │
└─────────────────────────────────────┘
```

### 7.3 SYSTEM_CAPABILITIESとの連携

```python
# 現状のSYSTEM_CAPABILITIESを活用
SYSTEM_CAPABILITIES = {
    "chatwork_task_create": {
        "name": "ChatWorkタスク作成",
        "description": "...",
        "category": "task",
        "enabled": True,
        "trigger_examples": [...],
        "params_schema": {...},
        "handler": "handle_chatwork_task_create",
        "requires_confirmation": False,
        # ★ 追加: 脳用のメタデータ
        "intent_keywords": ["タスク", "追加", "作成", "依頼", "お願い"],
        "priority": 3,  # 判断の優先順位
        "risk_level": "low",  # 確認要否の判断に使用
    },
    # ... 他の機能
}
```

### 7.4 機能選択のスコアリング

```python
def score_capability(
    capability: dict,
    understanding: UnderstandingResult
) -> float:
    """
    機能の適合度をスコアリング

    スコア = キーワードマッチ(40%) + 意図マッチ(30%) + 文脈マッチ(30%)
    """
    score = 0.0

    # キーワードマッチ（40%）
    keywords = capability.get("intent_keywords", [])
    matched = sum(1 for kw in keywords if kw in understanding.raw_message)
    score += (matched / len(keywords)) * 0.4 if keywords else 0.0

    # 意図マッチ（30%）
    if understanding.intent in capability.get("trigger_examples", []):
        score += 0.3

    # 文脈マッチ（30%）
    if capability["category"] == understanding.context_category:
        score += 0.3

    return score
```

### 7.5 確認モードの実装

```python
@dataclass
class ConfirmationRequest:
    """確認リクエスト"""

    question: str                      # 確認の質問
    options: List[str]                 # 選択肢
    default_option: Optional[str]      # デフォルト選択肢
    timeout_seconds: int = 300         # タイムアウト（5分）

    # 確認後の処理
    on_confirm_action: str             # 確認OKの場合のアクション
    on_confirm_params: dict            # 確認OKの場合のパラメータ

    def to_message(self) -> str:
        """ChatWorkメッセージに変換"""
        msg = f"🤔 確認させてほしいウル！\n\n{self.question}\n\n"
        for i, option in enumerate(self.options, 1):
            msg += f"{i}. {option}\n"
        msg += "\n番号で教えてほしいウル🐺"
        return msg
```

### 7.6 複数アクションの判断

```python
def detect_multiple_actions(
    understanding: UnderstandingResult
) -> List[ActionCandidate]:
    """
    1つのメッセージから複数のアクションを検出

    例: 「崇樹にタスク追加して、あと自分のタスク教えて」
    → [タスク作成, タスク検索] の2つ
    """
    actions = []

    # 接続詞で分割
    segments = split_by_conjunction(understanding.raw_message)

    for segment in segments:
        # 各セグメントで意図を推論
        segment_understanding = understand_segment(segment, understanding.context)
        action = select_action(segment_understanding)
        if action:
            actions.append(action)

    return actions
```

---

## 8. 実行層（Execution Layer）

### 8.1 概要

実行層は、判断層からの指令に基づいて**各ハンドラーを呼び出し、結果を統合**する層です。

**設計思想:**
- ハンドラーは「実行するだけ」で判断ロジックを持たない
- 結果は脳に戻り、脳が最終的なレスポンスを生成
- エラーハンドリングも脳の責務

### 8.2 実行フロー

```
判断層からの実行コマンド
          │
          ▼
┌─────────────────────────────────────┐
│ Step 1: ハンドラー取得              │
│ - HANDLERSマッピングから取得        │
│ - 存在しない場合はエラー            │
└─────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────┐
│ Step 2: パラメータ検証              │
│ - 必須パラメータのチェック          │
│ - 型の検証                          │
│ - 不足時は確認モードに戻る          │
└─────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────┐
│ Step 3: ハンドラー実行              │
│ - try-except でラップ               │
│ - タイムアウト設定（30秒）          │
│ - 結果を構造化して返す              │
└─────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────┐
│ Step 4: 結果の統合                  │
│ - 成功時: レスポンスメッセージ生成  │
│ - 失敗時: エラーハンドリング        │
│ - 監査ログ記録                      │
└─────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────┐
│ Step 5: 状態更新                    │
│ - 会話履歴に追加                    │
│ - 必要に応じて記憶更新              │
│ - 次のステップがあれば状態遷移      │
└─────────────────────────────────────┘
```

### 8.3 ハンドラーインターフェース

```python
class HandlerResult:
    """ハンドラーの実行結果"""

    success: bool                      # 成功/失敗
    message: str                       # 表示するメッセージ
    data: Optional[dict]               # 追加データ

    # 次のアクション
    next_action: Optional[str]         # 続けて実行するアクション
    next_params: Optional[dict]        # 次のアクションのパラメータ

    # 状態変更
    update_state: Optional[dict]       # 状態の更新内容

    # 提案
    suggestions: List[str]             # 関連する提案（先読み）


def handler_interface(
    params: dict,
    room_id: str,
    account_id: str,
    sender_name: str,
    context: BrainContext
) -> HandlerResult:
    """
    全ハンドラーが実装すべきインターフェース

    Args:
        params: 判断層から渡されたパラメータ
        room_id: ChatWorkルームID
        account_id: ユーザーのアカウントID
        sender_name: 送信者名
        context: 脳から渡されたコンテキスト

    Returns:
        HandlerResult: 実行結果
    """
    pass
```

### 8.4 エラーハンドリング戦略

| エラー種別 | 対応 | ユーザーへの表示 |
|-----------|------|----------------|
| パラメータ不足 | 確認モードに遷移 | 「〇〇を教えてほしいウル」|
| 外部API失敗 | リトライ（3回まで） | 「ちょっと待ってほしいウル」|
| タイムアウト | 中断＋通知 | 「時間がかかっているウル」|
| 権限エラー | 説明＋代替案 | 「この操作はできないウル」|
| 予期せぬエラー | ログ＋一般エラー | 「エラーが発生したウル」|

### 8.5 先読み提案の実装

```python
def generate_suggestions(
    action: str,
    result: HandlerResult,
    context: BrainContext
) -> List[str]:
    """
    実行結果に基づいて、次に役立つ提案を生成

    例: タスク作成後 → 「リマインドを設定する？」「他にもタスクある？」
    """
    suggestions = []

    if action == "chatwork_task_create" and result.success:
        suggestions.append("このタスクにリマインドを設定しようか？")
        if context.recent_tasks:
            suggestions.append("他にも追加するタスクはある？")

    elif action == "chatwork_task_search" and result.success:
        if result.data.get("overdue_count", 0) > 0:
            suggestions.append("期限超過のタスクがあるけど、対応する？")

    return suggestions[:3]  # 最大3つ
```

---

## 9. 状態管理層（State Management Layer）

### 9.1 概要

状態管理層は、**マルチステップの対話フローを統一的に管理**する層です。

**設計思想:**
- 各機能が独自に状態を持つのではなく、脳が一元管理
- 状態は明示的に遷移し、タイムアウトで自動クリア
- どの状態からでも「キャンセル」で脱出可能

### 9.2 現状の問題点

| 機能 | 現状の状態管理 | 問題点 |
|------|--------------|--------|
| 目標設定 | goal_setting_sessions テーブル | 独自のセッション管理 |
| アナウンス | scheduled_announcements.status='pending' | 独自のpending管理 |
| タスク作成 | pending_tasks (インメモリ?) | 統一されていない |

### 9.3 統一状態管理テーブル

```sql
-- 会話状態管理テーブル（新規）
CREATE TABLE brain_conversation_states (
    -- 識別
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    room_id VARCHAR(50) NOT NULL,
    user_id VARCHAR(50) NOT NULL,  -- ChatWork account_id

    -- 状態
    state_type VARCHAR(50) NOT NULL,  -- 'normal', 'goal_setting', 'announcement', 'confirmation', 'task_pending'
    state_step VARCHAR(50),            -- 'intro', 'why', 'what', 'how', 'confirm'
    state_data JSONB DEFAULT '{}',     -- 状態固有のデータ

    -- 元の機能への参照
    reference_type VARCHAR(50),        -- 'goal_session', 'announcement', 'task'
    reference_id UUID,                 -- 参照先のID

    -- タイムアウト
    expires_at TIMESTAMPTZ NOT NULL,   -- この時刻を過ぎたら自動クリア
    timeout_minutes INT DEFAULT 30,

    -- 監査
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- ユニーク制約（1ユーザー1ルームに1状態）
    CONSTRAINT unique_user_room_state UNIQUE(organization_id, room_id, user_id),

    -- 状態タイプの制約
    CONSTRAINT check_state_type CHECK (state_type IN (
        'normal',           -- 通常状態（状態なし）
        'goal_setting',     -- 目標設定対話中
        'announcement',     -- アナウンス確認中
        'confirmation',     -- 確認待ち
        'task_pending',     -- タスク作成待ち
        'multi_action'      -- 複数アクション実行中
    ))
);

-- インデックス
CREATE INDEX idx_brain_states_user ON brain_conversation_states(organization_id, room_id, user_id);
CREATE INDEX idx_brain_states_expires ON brain_conversation_states(expires_at) WHERE state_type != 'normal';
CREATE INDEX idx_brain_states_ref ON brain_conversation_states(reference_type, reference_id);
```

### 9.4 状態遷移図

```
                              ┌─────────────┐
                              │   normal    │
                              │ （通常状態） │
                              └──────┬──────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        │                            │                            │
        ▼                            ▼                            ▼
┌───────────────┐          ┌───────────────┐          ┌───────────────┐
│ goal_setting  │          │ announcement  │          │ confirmation  │
│ (目標設定中)  │          │ (アナウンス)  │          │ (確認待ち)    │
│               │          │               │          │               │
│ intro→why    │          │ pending       │          │ waiting       │
│ →what→how    │          │ →confirmed   │          │ →confirmed   │
│ →complete    │          │ →executed    │          │ →executed    │
└───────────────┘          └───────────────┘          └───────────────┘
        │                            │                            │
        │   「やめる」「キャンセル」   │                            │
        └────────────────────────────┼────────────────────────────┘
                                     │
                                     ▼
                              ┌─────────────┐
                              │   normal    │
                              │ （通常状態） │
                              └─────────────┘
```

### 9.5 状態管理API

```python
class BrainStateManager:
    """脳の状態管理"""

    def __init__(self, pool, org_id: str):
        self.pool = pool
        self.org_id = org_id

    async def get_current_state(
        self,
        room_id: str,
        user_id: str
    ) -> Optional[ConversationState]:
        """
        現在の状態を取得

        タイムアウトしている場合は自動的にクリアしてNoneを返す
        """
        pass

    async def transition_to(
        self,
        room_id: str,
        user_id: str,
        new_state: str,
        step: str = None,
        data: dict = None,
        reference_type: str = None,
        reference_id: str = None,
        timeout_minutes: int = 30
    ) -> ConversationState:
        """
        状態を遷移

        既存の状態がある場合は上書き（UPSERT）
        """
        pass

    async def clear_state(
        self,
        room_id: str,
        user_id: str,
        reason: str = "user_cancel"
    ) -> None:
        """
        状態をクリア（通常状態に戻す）

        Args:
            reason: クリア理由（user_cancel, timeout, completed, error）
        """
        pass

    async def update_step(
        self,
        room_id: str,
        user_id: str,
        new_step: str,
        additional_data: dict = None
    ) -> ConversationState:
        """
        現在の状態内でステップを進める

        例: goal_setting の why → what
        """
        pass
```

### 9.6 キャンセル検出

```python
CANCEL_KEYWORDS = [
    "やめる", "やめて", "キャンセル", "cancel",
    "中止", "止めて", "やっぱり", "やっぱいい",
    "もういい", "いらない", "やめた", "やめます",
    "終わり", "終了", "おわり"
]

def is_cancel_request(message: str) -> bool:
    """キャンセルリクエストかどうかを判定"""
    normalized = message.strip().lower()
    return any(kw in normalized for kw in CANCEL_KEYWORDS)
```

---

## 10. データベース設計

### 10.1 新規テーブル一覧

| テーブル名 | 目的 | 行数見込み |
|-----------|------|-----------|
| brain_conversation_states | 会話状態管理 | ユーザー数 × 1 |
| brain_decision_logs | 判断ログ（監査用） | 会話数 × 1 |
| brain_memory_access_logs | 記憶アクセスログ | 会話数 × N |

### 10.2 brain_conversation_states（詳細）

前述の「9.3 統一状態管理テーブル」を参照。

### 10.3 brain_decision_logs

```sql
-- 脳の判断ログ（監査・分析用）
CREATE TABLE brain_decision_logs (
    -- 識別
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 入力情報
    room_id VARCHAR(50) NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    user_message TEXT NOT NULL,

    -- 理解層の結果
    understanding_result JSONB NOT NULL,  -- 推論した意図、エンティティ等
    understanding_confidence DECIMAL(4,3),

    -- 判断層の結果
    selected_action VARCHAR(100) NOT NULL,
    action_params JSONB,
    decision_confidence DECIMAL(4,3),
    decision_reasoning TEXT,

    -- 確認モード
    required_confirmation BOOLEAN DEFAULT FALSE,
    confirmation_question TEXT,

    -- 実行結果
    execution_success BOOLEAN,
    execution_error TEXT,

    -- パフォーマンス
    understanding_time_ms INT,
    decision_time_ms INT,
    execution_time_ms INT,
    total_time_ms INT,

    -- 監査
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal'
);

-- インデックス
CREATE INDEX idx_brain_decision_org ON brain_decision_logs(organization_id);
CREATE INDEX idx_brain_decision_user ON brain_decision_logs(organization_id, user_id);
CREATE INDEX idx_brain_decision_action ON brain_decision_logs(selected_action);
CREATE INDEX idx_brain_decision_created ON brain_decision_logs(created_at DESC);
CREATE INDEX idx_brain_decision_low_confidence ON brain_decision_logs(decision_confidence)
    WHERE decision_confidence < 0.7;
```

### 10.4 既存テーブルとの関連

```
┌─────────────────────────────────────────────────────────────────────┐
│                         脳アーキテクチャ                            │
│                                                                     │
│  ┌─────────────────────┐  ┌─────────────────────┐                  │
│  │ brain_conversation_ │  │ brain_decision_     │                  │
│  │ states              │  │ logs                │                  │
│  │ (状態管理)          │  │ (判断ログ)          │                  │
│  └──────────┬──────────┘  └─────────────────────┘                  │
│             │                                                       │
└─────────────┼───────────────────────────────────────────────────────┘
              │
              │ 参照
              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      既存テーブル群                                  │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ goal_setting │  │ scheduled_   │  │ chatwork_    │              │
│  │ _sessions    │  │ announcements│  │ tasks        │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ conversation │  │ user_        │  │ soulkun_     │              │
│  │ _summaries   │  │ preferences  │  │ knowledge    │              │
│  │ (B1)         │  │ (B2)         │  │              │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ persons      │  │ documents    │  │ soulkun_     │              │
│  │              │  │ (Phase 3)    │  │ insights     │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 11. API設計

### 11.1 内部API（脳の各層間）

脳の各層間はPythonクラス間の呼び出しで実装。外部APIは不要。

```python
# lib/brain/core.py

class SoulkunBrain:
    """ソウルくんの脳（中央処理装置）"""

    def __init__(self, pool, org_id: str):
        self.pool = pool
        self.org_id = org_id
        self.memory = BrainMemoryAccess(pool, org_id)
        self.state_manager = BrainStateManager(pool, org_id)

    async def process_message(
        self,
        message: str,
        room_id: str,
        account_id: str,
        sender_name: str
    ) -> BrainResponse:
        """
        メッセージを処理して応答を返す

        これが脳の唯一のエントリーポイント。
        全ての入力はここを通る。
        """

        # 1. 記憶層: コンテキスト取得
        context = await self.memory.get_full_context(
            user_id=account_id,
            room_id=room_id
        )

        # 2. 状態チェック: マルチステップセッション中？
        current_state = await self.state_manager.get_current_state(
            room_id=room_id,
            user_id=account_id
        )

        # 2.1 キャンセルリクエスト？
        if is_cancel_request(message) and current_state:
            await self.state_manager.clear_state(room_id, account_id, "user_cancel")
            return BrainResponse(
                message="了解ウル！キャンセルしたウル🐺",
                action_taken="cancel_session"
            )

        # 2.2 セッション中なら、そのフローを継続
        if current_state and current_state.is_active:
            return await self._continue_session(
                message, current_state, context, room_id, account_id, sender_name
            )

        # 3. 理解層: 意図を推論
        understanding = await self._understand(message, context)

        # 4. 判断層: アクションを決定
        decision = await self._decide(understanding, context)

        # 4.1 確認が必要？
        if decision.needs_confirmation:
            # 確認状態に遷移
            await self.state_manager.transition_to(
                room_id=room_id,
                user_id=account_id,
                new_state="confirmation",
                data={
                    "pending_action": decision.action,
                    "pending_params": decision.params,
                    "confirmation_options": decision.confirmation_options
                }
            )
            return BrainResponse(
                message=decision.confirmation_question,
                action_taken="request_confirmation"
            )

        # 5. 実行層: アクションを実行
        result = await self._execute(decision, context, room_id, account_id, sender_name)

        # 6. 記憶更新
        await self._update_memory(message, result, context)

        # 7. 判断ログ記録
        await self._log_decision(
            message, understanding, decision, result, room_id, account_id
        )

        return result
```

### 11.2 chatwork_webhookとの統合

```python
# chatwork-webhook/main.py の変更点

def chatwork_webhook(request):
    """
    Webhookエントリーポイント

    変更点: 全てのメッセージを脳に渡す
    """
    # ... 署名検証等は変更なし ...

    # ★ 変更: バイパスルートを削除し、全て脳に渡す

    # 脳のインスタンスを取得
    brain = get_brain_instance(org_id)

    # 脳にメッセージを渡す
    response = await brain.process_message(
        message=clean_message,
        room_id=room_id,
        account_id=sender_account_id,
        sender_name=sender_name
    )

    # 応答を送信
    send_chatwork_message(room_id, response.message, sender_account_id)

    return jsonify({"status": "ok"})
```

---

## 12. 移行計画

### 12.1 フェーズ概要

| Phase | 名称 | 内容 | 工数 | リスク |
|-------|------|------|------|--------|
| **A** | バイパス排除 | 全入力を脳経由に変更 | 20h | 高 |
| **B** | 記憶統合 | Memory Frameworkを脳に統合 | 15h | 中 |
| **C** | 状態管理統一 | brain_conversation_statesに統合 | 15h | 中 |
| **D** | 理解層強化 | 曖昧表現解決、確認モード | 20h | 低 |
| **E** | 先読み提案 | 提案機能の追加 | 10h | 低 |
| **合計** | | | **80h** | |

### 12.2 Phase A: バイパス排除（最優先）

**目的:** 全ての入力が脳を通るようにする

**現状のバイパスルート:**
1. `handle_pending_task_followup()` - pending taskのフォローアップ
2. 目標設定セッション中の判定 (`has_active_goal_session()`)
3. ローカルコマンド判定 (`match_local_command()`)
4. アナウンス確認中の判定 (`_get_pending_announcement()`)

**移行手順:**

```python
# Step 1: 脳クラスの作成
# lib/brain/core.py を作成

# Step 2: chatwork_webhookの修正
# バイパスルートを脳に統合

# Step 3: Feature Flag で切り替え
USE_BRAIN_ARCHITECTURE = os.environ.get("USE_BRAIN_ARCHITECTURE", "false").lower() == "true"

if USE_BRAIN_ARCHITECTURE:
    # 新アーキテクチャ: 全て脳経由
    response = await brain.process_message(...)
else:
    # 旧アーキテクチャ: 既存のバイパスルート
    # ... 既存コード ...
```

**ロールバック:**
- `USE_BRAIN_ARCHITECTURE=false` で即座に旧アーキテクチャに戻せる

### 12.3 Phase B: 記憶統合

**目的:** 脳が全ての記憶にアクセスできるようにする

**統合対象:**
1. conversation_history (Firestore) → BrainMemoryAccess
2. conversation_summaries (B1) → BrainMemoryAccess
3. user_preferences (B2) → BrainMemoryAccess
4. persons → BrainMemoryAccess
5. chatwork_tasks → BrainMemoryAccess
6. goals → BrainMemoryAccess
7. soulkun_knowledge → BrainMemoryAccess
8. soulkun_insights → BrainMemoryAccess

**移行手順:**

```python
# Step 1: BrainMemoryAccessクラスの実装
# lib/brain/memory_access.py

# Step 2: 各記憶タイプのアダプター作成
# 既存のテーブル/Firestoreへのアクセスをラップ

# Step 3: ai_commanderのプロンプトを更新
# 統合されたコンテキストを使用
```

### 12.4 Phase C: 状態管理統一

**目的:** マルチステップセッションを脳で統一管理

**移行対象:**
1. goal_setting_sessions → brain_conversation_states
2. scheduled_announcements.status='pending' → brain_conversation_states
3. pending_tasks → brain_conversation_states

**移行手順:**

```python
# Step 1: brain_conversation_statesテーブル作成
# マイグレーション実行

# Step 2: 既存のセッションをマイグレーション
# goal_setting_sessions の active なセッションを brain_conversation_states にコピー

# Step 3: 各ハンドラーを更新
# 独自の状態管理からBrainStateManagerに切り替え
```

### 12.5 Phase D: 理解層強化

**目的:** 曖昧表現の解決、確認モードの実装

**実装内容:**
1. 省略補完ロジック
2. 代名詞解決ロジック
3. 確認モードの実装
4. 確認応答のハンドリング

### 12.6 Phase E: 先読み提案

**目的:** アクション完了後の関連提案

**実装内容:**
1. アクション別の提案テンプレート
2. コンテキストに基づく動的提案
3. 提案の表示制御（頻度制限等）

---

## 13. テスト戦略

### 13.1 テスト種別とカバレッジ目標

| テストレベル | 目的 | カバレッジ目標 |
|------------|------|--------------|
| 単体テスト | 各層の個別機能 | 80%以上 |
| 統合テスト | 層間の連携 | 主要シナリオ100% |
| E2Eテスト | 実際のユーザーフロー | 主要フロー100% |
| 回帰テスト | 既存機能の維持 | 既存テスト全パス |

### 13.2 単体テストケース

**理解層:**
- 意図推論のテスト（20ケース）
- 省略補完のテスト（15ケース）
- 代名詞解決のテスト（10ケース）
- 確認要否判定のテスト（10ケース）

**判断層:**
- 機能選択のテスト（30ケース）
- スコアリングのテスト（15ケース）
- 複数アクション検出のテスト（10ケース）

**状態管理:**
- 状態遷移のテスト（20ケース）
- タイムアウトのテスト（5ケース）
- キャンセル検出のテスト（10ケース）

**合計: 145ケース以上**

### 13.3 統合テストシナリオ

```python
@pytest.mark.integration
async def test_goal_setting_flow():
    """目標設定の完全フロー"""
    brain = SoulkunBrain(pool, org_id)

    # Step 1: 目標設定開始
    response1 = await brain.process_message(
        message="目標を設定したい",
        room_id="room1",
        account_id="user1",
        sender_name="テストユーザー"
    )
    assert "なぜ" in response1.message  # WHYの質問

    # Step 2: WHYに回答
    response2 = await brain.process_message(
        message="売上を上げたいから",
        room_id="room1",
        account_id="user1",
        sender_name="テストユーザー"
    )
    assert "何を" in response2.message  # WHATの質問

    # Step 3: キャンセル
    response3 = await brain.process_message(
        message="やっぱりやめる",
        room_id="room1",
        account_id="user1",
        sender_name="テストユーザー"
    )
    assert "キャンセル" in response3.message

    # 状態がクリアされていることを確認
    state = await brain.state_manager.get_current_state("room1", "user1")
    assert state is None or state.state_type == "normal"
```

### 13.4 回帰テスト

既存の機能が壊れていないことを確認:

- タスク作成: 10ケース
- タスク検索: 10ケース
- タスク完了: 5ケース
- ナレッジ検索: 10ケース
- 人物情報: 10ケース
- 目標設定: 15ケース
- アナウンス: 15ケース

**合計: 75ケース**

---

## 14. リスクと対策

### 14.1 リスク一覧

| # | リスク | 影響度 | 発生確率 | 対策 |
|---|--------|--------|---------|------|
| 1 | APIコスト増加 | 中 | 高 | キャッシュ、軽量モデル活用 |
| 2 | レイテンシ増加 | 中 | 高 | 並列処理、段階的表示 |
| 3 | 既存機能のデグレ | 高 | 中 | Feature Flag、回帰テスト |
| 4 | 状態管理の不整合 | 高 | 中 | トランザクション、冪等性 |
| 5 | AI判断の誤り | 中 | 中 | 確認モード、ログ分析 |

### 14.2 詳細対策

**リスク1: APIコスト増加**
- 記憶のキャッシュ（Redis）で重複呼び出しを削減
- 軽量モデル（Haiku相当）を理解層に使用
- 会話履歴は要約を活用して入力トークンを削減

**リスク2: レイテンシ増加**
- 記憶取得を並列実行
- 「考え中...」の表示で体感を改善
- 優先度の低い処理は非同期化

**リスク3: 既存機能のデグレ**
- `USE_BRAIN_ARCHITECTURE` Feature Flagで段階的導入
- 既存の回帰テスト75ケースを全パス必須
- 本番でも旧アーキテクチャへ即座にロールバック可能

**リスク4: 状態管理の不整合**
- 状態遷移はトランザクション内で実行
- タイムアウトによる自動クリア
- 冪等性キーで二重処理防止

**リスク5: AI判断の誤り**
- confidence < 0.7 で確認モード発動
- 判断ログを全て記録し、後から分析可能
- ユーザーからの「違う」を検出して学習

---

## 15. 実装チェックリスト

### 15.1 Phase A: バイパス排除

- [ ] `lib/brain/` ディレクトリ作成
- [ ] `lib/brain/__init__.py` 作成
- [ ] `lib/brain/core.py` - SoulkunBrainクラス実装
- [ ] `lib/brain/models.py` - データモデル定義
- [ ] chatwork-webhook/main.py のバイパスルート削除
- [ ] Feature Flag `USE_BRAIN_ARCHITECTURE` 追加
- [ ] 回帰テスト75ケース全パス確認
- [ ] 本番デプロイ（Feature Flag OFF）
- [ ] 段階的有効化（管理部のみ → 全社）

### 15.2 Phase B: 記憶統合

- [ ] `lib/brain/memory_access.py` - BrainMemoryAccess実装
- [ ] 会話履歴アダプター実装
- [ ] 会話要約アダプター実装
- [ ] ユーザー嗜好アダプター実装
- [ ] 人物情報アダプター実装
- [ ] タスク情報アダプター実装
- [ ] 目標情報アダプター実装
- [ ] 会社知識アダプター実装
- [ ] インサイトアダプター実装
- [ ] BrainContextテスト20ケース

### 15.3 Phase C: 状態管理統一

- [ ] brain_conversation_states テーブル作成
- [ ] マイグレーションスクリプト作成
- [ ] `lib/brain/state_manager.py` - BrainStateManager実装
- [ ] 目標設定セッション移行
- [ ] アナウンス確認移行
- [ ] タスク作成待ち移行
- [ ] キャンセル検出実装
- [ ] タイムアウト処理実装
- [ ] 状態遷移テスト20ケース

### 15.4 Phase D: 理解層強化

- [ ] `lib/brain/understanding.py` - 理解層実装
- [ ] 意図推論プロンプト作成
- [ ] 省略補完ロジック実装
- [ ] 代名詞解決ロジック実装
- [ ] 確認モード実装
- [ ] 確認応答ハンドリング実装
- [ ] 理解層テスト55ケース

### 15.5 Phase E: 先読み提案

- [ ] `lib/brain/suggestions.py` - 提案生成実装
- [ ] アクション別提案テンプレート定義
- [ ] 動的提案生成ロジック実装
- [ ] 提案表示制御実装
- [ ] 提案テスト15ケース

### 15.6 最終確認

- [ ] 全ユニットテスト145ケース以上
- [ ] 全統合テストパス
- [ ] 全回帰テスト75ケースパス
- [ ] 本番デプロイ完了
- [ ] CLAUDE.md更新
- [ ] 設計書更新

---

## 16. 付録

### 16.1 用語集

| 用語 | 定義 |
|------|------|
| 脳（Brain） | ソウルくんの中央処理装置。全ての入力を受け取り、記憶を参照し、判断し、実行を指令する |
| 記憶層 | 脳が参照する全ての記憶を統一的に管理する層 |
| 理解層 | ユーザーの入力から真の意図を推論する層 |
| 判断層 | どの機能を実行するかを決定する層 |
| 実行層 | 各ハンドラーを呼び出し、結果を統合する層 |
| 状態管理層 | マルチステップの対話フローを管理する層 |
| バイパスルート | 脳を経由せずに直接機能を呼び出すルート（禁止） |
| 確認モード | 確信度が低い場合にユーザーに確認を求める状態 |
| コンテキスト | 脳が判断に使用する統合された情報 |

### 16.2 設計書間の参照関係

```
13_brain_architecture.md（本設計書）
    │
    ├─→ 01_philosophy_and_principles.md（設計原則）
    │     └─ 1.2 設計原則「脳みそ先行」
    │
    ├─→ 10_phase2_b_memory_framework.md（記憶層）
    │     └─ B1〜B4の全機能を記憶層として統合
    │
    ├─→ 10_phase2c_mvv_secretary.md（判断軸）
    │     └─ MVV整合性チェックを判断層に統合
    │
    ├─→ 05_phase2-5_goal_achievement.md（目標設定）
    │     └─ goal_setting_sessionsを状態管理層に統合
    │
    ├─→ 09_implementation_standards.md（実装規約）
    │     └─ 10の鉄則を全層で遵守
    │
    └─→ 03_database_design.md（DB設計）
          └─ 新規テーブルを追加
```

### 16.3 変更履歴

| 日付 | バージョン | 変更内容 | 変更者 |
|------|-----------|---------|--------|
| 2026-01-26 | v1.0.0 | 初版作成 | Claude Code |

---

**設計書 終了**

---

**[📁 目次に戻る](00_README.md)**
