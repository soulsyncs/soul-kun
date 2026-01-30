# 設計書リファクタリング計画書

**バージョン:** v1.0.0
**作成日:** 2026-01-30
**作成者:** Claude Code
**承認者:** カズさん（代表）

---

## 1. 背景と目的

### 1.1 現状の問題

| 問題 | 影響 |
|------|------|
| 設計書が46ファイルに分散 | どれが「真実」か分からない |
| キーワードマッチ方式（13章）が中心 | 「全然まともに会話できてない」状態 |
| 重複・矛盾する記述が存在 | 設計判断に迷いが生じる |
| 古い設計書が残っている | メンテナンスコストが高い |

### 1.2 目指す姿

```
【Before】
46ファイル → どれが真実か分からない
キーワードマッチ方式が中心

【After】
3層構造 → 明確な役割分担
LLM常駐型（25章）が主軸
「推論ありきの脳」を設計の中心に
```

### 1.3 ゴール

> **「社長の分身であり、スタッフの最高の優秀な秘書、全員の秘書であり、人がやらなくてもいいものをテクノロジーが代わりにやってくれるソウルくん」**

このゴールを実現するための設計体系を構築する。

---

## 2. 新しい設計書体系

### 2.1 3層構造

```
設計書体系（新）
│
├─【第1層：設計OS】（2ファイル）
│   ├── CLAUDE.md              ← Claude Code用の設計OS
│   └── docs/25_llm_native_brain_architecture.md  ← 脳設計の主軸
│
├─【第2層：基盤設計】（5ファイル）
│   ├── 01_philosophy_and_principles.md  ← 哲学・原則
│   ├── 03_database_design.md            ← DB設計
│   ├── 04_api_and_security.md           ← API・セキュリティ
│   ├── 09_implementation_standards.md   ← 実装規約
│   └── security_and_bcp_guide.md        ← セキュリティ・BCP
│
├─【第3層：機能別設計】（20ファイル）
│   ├── Phase 1-B〜Phase 4の各設計書
│   └── 組織論・フロントエンド設計等
│
└─【アーカイブ】（旧設計書・レポート類）
    └── archive/
```

### 2.2 役割定義

| 層 | 役割 | 参照タイミング |
|----|------|---------------|
| 第1層 | 全ての判断基準 | 常に参照 |
| 第2層 | 技術基盤の定義 | 設計・実装時 |
| 第3層 | 機能別の詳細仕様 | 該当機能の実装時 |
| アーカイブ | 過去の意思決定の記録 | 経緯確認時のみ |

---

## 3. ファイル分類（全46ファイル）

### 3.1 第1層：設計OS（維持・強化）

| ファイル | 役割 | アクション |
|---------|------|-----------|
| CLAUDE.md | Claude Code用設計OS | 25章への参照を追加 |
| 25_llm_native_brain_architecture.md | 脳設計の主軸 | 統合対象の内容を吸収 |

### 3.2 統合対象（25章に吸収後、アーカイブ）

| ファイル | 内容 | 25章の統合先 |
|---------|------|-------------|
| 00_Goals_and_Principles.md | 設計憲法 | 第3章（設計原則）に統合 |
| 13_brain_architecture.md | 旧・脳設計 | 第5章（アーキテクチャ）に統合 |
| 14_brain_refactoring_plan.md | 脳リファクタリング計画 | 第12章（移行計画）に統合 |
| 15_phase2d_ceo_learning.md | CEO学習層 | 第6章（Guardian Layer）に統合 |
| 17_brain_completion_roadmap.md | 脳完成ロードマップ | 第12章（移行計画）に統合 |
| 18_phase2e_learning_foundation.md | 学習基盤 | 第6章（Learning Layer）に統合 |
| 19_ultimate_brain_architecture.md | 究極の脳設計 | 既に25章に統合済み |
| 20_next_generation_capabilities.md | 次世代能力 | 第17章（付録）に統合 |
| 21_phase2l_execution_excellence.md | 実行力強化 | 第6章（Execution Layer）に統合 |
| 23_proactive_violation_analysis.md | 違反分析 | 第9章（リスク対策）に統合 |
| 24_polished_system_prompt.md | システムプロンプト | 第8章（System Prompt）に統合 |
| brain_capability_integration_design.md | 脳機能統合 | 第6章に統合 |

### 3.3 第2層：基盤設計（維持）

| ファイル | 役割 | アクション |
|---------|------|-----------|
| 01_philosophy_and_principles.md | 哲学・原則 | 維持（最高レベルの価値観） |
| 03_database_design.md | DB設計 | 維持（スキーマ定義のSSOT） |
| 04_api_and_security.md | API・セキュリティ | 維持（セキュリティ規約） |
| 09_implementation_standards.md | 実装規約 | 維持（開発者向け必須） |
| security_and_bcp_guide.md | セキュリティ・BCP | 維持（営業・説明用） |

### 3.4 第3層：機能別設計（維持）

| ファイル | 役割 | アクション |
|---------|------|-----------|
| 02_phase_overview.md | Phase構成全体図 | 維持 |
| 05_phase_1b_task_detection.md | Phase 1-Bタスク検知 | 維持 |
| 05_phase2-5_goal_achievement.md | Phase 2.5目標達成支援 | 維持 |
| 05_phase2-5_soulkun_prompts.md | プロンプト集 | 維持 |
| 05_phase3_knowledge_detailed_design.md | Phase 3ナレッジ | 維持 |
| 06_phase_3-5_org_hierarchy.md | Phase 3.5組織階層 | 維持 |
| 06_phase2_a1_pattern_detection.md | Phase 2A1パターン検出 | 維持 |
| 06_phase3_google_drive_integration.md | Phase 3 Google Drive | 維持 |
| 07_phase_c_meetings.md | Phase C会議系 | 維持 |
| 07_phase2_a2_personalization_detection.md | Phase 2A2属人化検出 | 維持 |
| 08_phase_4_and_bpaas.md | Phase 4・BPaaS | 維持 |
| 08_phase2_a3_bottleneck_detection.md | Phase 2A3ボトルネック | 維持 |
| 09_phase2_a4_emotion_detection.md | Phase 2A4感情検出 | 維持 |
| 10_phase2_b_memory_framework.md | Phase 2B記憶 | 維持 |
| 10_phase2c_mvv_secretary.md | Phase 2C MVV | 維持 |
| 11_organizational_theory_guidelines.md | 組織論行動指針 | 維持 |
| 12_org_chart_frontend_design.md | org-chartフロントエンド | 維持 |
| PHASE_3-5_DETAILED_DESIGN.md | Phase 3.5詳細設計 | 維持 |
| PHASE_3-5_CHECKLIST.md | Phase 3.5チェックリスト | 維持 |
| PHASE3_TRIAL_OPERATION_GUIDE.md | Phase 3試験運用 | 維持 |
| ENVIRONMENT_VARIABLES.md | 環境変数 | 維持 |

### 3.5 アーカイブ対象

| ファイル | 理由 | アクション |
|---------|------|-----------|
| 00_README.md | 新しい目次に置き換え | archive/に移動 |
| 05_phase3_knowledge_detailed_design_VERIFICATION.md | 検証用一時ファイル | archive/に移動 |
| 10_troubleshooting_and_faq.md | 実装時に動的生成すべき | archive/に移動 |
| 16_old_code_removal_plan.md | 実装完了済み | archive/に移動 |
| CHANGELOG.md | git logで参照可能 | archive/に移動 |
| lib_sync_audit_report_20260127.md | 一時的レポート | archive/に移動 |
| README.md | 重複ファイル | archive/に移動 |

---

## 4. 統合作業の詳細

### 4.1 25章への統合内容

#### 4.1.1 00_Goals_and_Principles.md → 第3章

**統合内容:**
- 10の鉄則
- 7つの脳鉄則（8つに更新）
- 権限判定の責務分離
- データソース優先順位（Truth順位）

**統合方法:**
- 25章3.6節に「既存設計との整合」として追加
- 重複部分は25章の記述を優先

#### 4.1.2 13_brain_architecture.md → 第5章

**統合内容:**
- 4層構造（記憶→理解→判断→実行）の概念
- 状態管理層の設計
- ハンドラーインターフェース

**統合方法:**
- 25章の6層構造との対応表を作成
- 旧設計から新設計への移行マッピング

#### 4.1.3 15_phase2d_ceo_learning.md → 第6章

**統合内容:**
- CEO教え機能
- Guardian Layer（ルールベース検証）

**統合方法:**
- 25章6.2節「Guardian Layer」に統合
- CEO教えはTool定義として整理

#### 4.1.4 18_phase2e_learning_foundation.md → 第6章

**統合内容:**
- 学習基盤
- フィードバックループ

**統合方法:**
- 25章の将来Phase（Phase N: Learning）として整理

#### 4.1.5 24_polished_system_prompt.md → 第8章

**統合内容:**
- System Prompt v2.0
- ペルソナ定義
- 応答スタイル

**統合方法:**
- 25章8章を拡充
- プロンプトテンプレートを付録に移動

---

## 5. CLAUDE.mdの更新内容

### 5.1 追加セクション

```markdown
## 14. 詳細が必要な時に見るファイル

| 知りたいこと | 見るファイル |
|-------------|-------------|
| 脳アーキテクチャ（LLM常駐型） | `docs/25_llm_native_brain_architecture.md` ← 主軸 |
| LLM Brain 憲法 | `docs/25_llm_native_brain_architecture.md` 第4章 |
| 設計の哲学 | `docs/01_philosophy_and_principles.md` |
| DB設計・テーブル定義 | `docs/03_database_design.md` |
| API設計・セキュリティ | `docs/04_api_and_security.md` |
| 実装規約 | `docs/09_implementation_standards.md` |
| 権限レベルの実装 | `api/app/services/access_control.py` |
| 進捗状況 | `PROGRESS.md` |
```

### 5.2 更新セクション

- セクション2「脳がすべて」に25章への参照を追加
- セクション13「脳アーキテクチャ」の参照先を13章→25章に変更

---

## 6. 00_README.md（新）の構成

```markdown
# ソウルくん設計書ガイド

## 設計書の読み方

### 3層構造

| 層 | 役割 | 主要ファイル |
|----|------|-------------|
| 第1層 | 設計OS | CLAUDE.md, 25章 |
| 第2層 | 基盤設計 | 01章, 03章, 04章, 09章 |
| 第3層 | 機能別設計 | Phase別設計書 |

### 最初に読むべきファイル

1. CLAUDE.md（設計OS）
2. 25章（LLM常駐型脳アーキテクチャ）
3. 必要に応じて機能別設計書

## ファイル一覧

（新しい分類に基づくファイル一覧）
```

---

## 7. 実行計画

### 7.1 フェーズ1: 準備

1. ✅ 計画書作成（本ドキュメント）
2. archive/ディレクトリ作成
3. 現在の状態をコミット（バックアップ）

### 7.2 フェーズ2: アーカイブ

1. アーカイブ対象をarchive/に移動
2. 統合対象をarchive/legacy/に移動（統合後）

### 7.3 フェーズ3: 統合

1. 25章に統合対象の内容を取り込む
2. 重複を解消し、整合性を確保
3. 参照関係を明確化

### 7.4 フェーズ4: 更新

1. CLAUDE.mdを更新
2. 00_README.mdを新構造に更新
3. 各設計書の参照先を更新

### 7.5 フェーズ5: 完了

1. 全変更をコミット
2. GitHubにプッシュ
3. PRを作成

---

## 8. リスクと対策

| リスク | 対策 |
|--------|------|
| 統合時に重要な情報が失われる | archive/に全て保存、git履歴で復元可能 |
| 参照先の変更で混乱が生じる | 移行期間を設け、段階的に切り替え |
| 実装中のコードに影響 | 設計書変更はドキュメントのみ、コード変更なし |

---

## 9. 成功指標

| 指標 | Before | After |
|------|--------|-------|
| 設計書ファイル数 | 46 | 27（+アーカイブ19） |
| 脳設計の主軸 | 13章（キーワードマッチ） | 25章（LLM常駐型） |
| 重複する記述 | 多数 | 解消 |
| 「どれを見ればいい？」 | 不明確 | 3層構造で明確 |

---

## 10. 承認

| 項目 | 承認者 | 日付 |
|------|--------|------|
| 計画承認 | カズさん | 2026-01-30 |
| 実行承認 | カズさん | 2026-01-30 |

---

**計画書 終了**
