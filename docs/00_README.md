# ソウルくん設計書ガイド v2.0

**作成日:** 2026-01-30
**最終更新:** 2026-01-30
**ステータス:** 確定

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | 設計書体系のナビゲーション・目次・クイックリファレンス |
| **書くこと** | 3層構造の説明、ファイル一覧、クイックリファレンス |
| **書かないこと** | 設計内容の詳細（→各設計書）、実装コード（→09章）、脳の詳細設計（→25章）、運用手順（→OPERATIONS_RUNBOOK） |
| **SoT（この文書が正）** | 設計書の分類と配置、「どこを見るべきか」のガイド |
| **Owner** | カズさん（代表） |
| **関連リンク** | [CLAUDE.md](../CLAUDE.md)、[25章](25_llm_native_brain_architecture.md)、[Design Coverage Matrix](DESIGN_COVERAGE_MATRIX.md) |

---

## 設計書の読み方

### 3層構造

ソウルくんの設計書は3層構造で整理されています。

```
設計書体系
│
├─【第1層：設計OS】─ 全ての判断基準（常に参照）
│   ├── CLAUDE.md（プロジェクトルート）
│   └── 25_llm_native_brain_architecture.md ← 脳設計の主軸
│
├─【第2層：基盤設計】─ 技術基盤の定義（設計・実装時）
│   ├── 01_philosophy_and_principles.md（哲学・原則）
│   ├── 03_database_design.md（DB設計）
│   ├── 04_api_and_security.md（API・セキュリティ）
│   └── 09_implementation_standards.md（実装規約）
│
├─【第3層：機能別設計】─ 機能の詳細仕様（該当機能の実装時）
│   ├── Phase 1-B〜Phase 4の各設計書
│   └── 組織論・フロントエンド設計等
│
└─【アーカイブ】─ 過去の設計書（経緯確認時のみ）
    └── archive/
        ├── legacy/（統合された旧設計書）
        └── （削除された設計書）
```

### 最初に読むべきファイル

1. **CLAUDE.md**（設計OS）- 全ての判断基準
2. **25_llm_native_brain_architecture.md**（脳設計の主軸）- LLM常駐型脳アーキテクチャ
3. 必要に応じて機能別設計書

---

## 第1層：設計OS

| ファイル | 役割 | 必読 |
|---------|------|------|
| **CLAUDE.md** | Claude Code用の設計OS、判断基準 | ★★★ |
| **25_llm_native_brain_architecture.md** | LLM常駐型脳アーキテクチャ設計書（主軸） | ★★★ |

### 25章の主要セクション

| 章 | 内容 |
|----|------|
| 第1章 | エグゼクティブサマリー |
| 第2章 | 設計進化の背景と目的 |
| 第3章 | 設計原則 |
| **第4章** | **LLM Brain 憲法（権限制限設計）** ← 最重要 |
| 第5章 | 新アーキテクチャ全体像 |
| 第6章 | 各層の詳細設計 |
| 第7章 | Tool定義（Function Calling） |
| 第8章 | System Promptの設計 |
| 第9章 | リスク対策の詳細 |
| 第10-16章 | データモデル、移行計画、テスト、コスト等 |
| 第17章 | 付録（System Prompt v2.0完全版、用語集等） |

---

## 第2層：基盤設計

| ファイル | 役割 | 用途 |
|---------|------|------|
| 01_philosophy_and_principles.md | 哲学・原則・MVV | 価値判断の根拠 |
| 03_database_design.md | DB設計・スキーマ定義 | テーブル設計時 |
| 04_api_and_security.md | API・セキュリティ規約 | API実装時 |
| 09_implementation_standards.md | 実装規約・コーディング規約 | コード実装時 |
| security_and_bcp_guide.md | セキュリティ・BCP説明資料 | 営業・説明時 |
| ENVIRONMENT_VARIABLES.md | 環境変数リファレンス | デプロイ時 |
| **OPERATIONS_RUNBOOK.md** | 運用Runbook（障害対応・緊急手順） | 本番運用時 |
| **DESIGN_COVERAGE_MATRIX.md** | 設計要素カバレッジ表（MECE保証） | 設計変更時 |

---

## 第3層：機能別設計

### Phase 1-B: タスク管理

| ファイル | 内容 |
|---------|------|
| 05_phase_1b_task_detection.md | タスク検知の詳細設計 |

### Phase 2: AI応答・検出機能

| ファイル | 内容 |
|---------|------|
| 06_phase2_a1_pattern_detection.md | パターン検出 |
| 07_phase2_a2_personalization_detection.md | 属人化検出 |
| 08_phase2_a3_bottleneck_detection.md | ボトルネック検出 |
| 09_phase2_a4_emotion_detection.md | 感情検出 |
| 10_phase2_b_memory_framework.md | 記憶フレームワーク |
| 10_phase2c_mvv_secretary.md | MVV・秘書機能 |

### Phase 2.5: 目標達成支援

| ファイル | 内容 |
|---------|------|
| 05_phase2-5_goal_achievement.md | 目標達成支援の詳細設計 |
| 05_phase2-5_soulkun_prompts.md | プロンプト集 |

### Phase 3: ナレッジ管理

| ファイル | 内容 |
|---------|------|
| 05_phase3_knowledge_detailed_design.md | ナレッジ系詳細設計 |
| 06_phase3_google_drive_integration.md | Google Drive連携 |
| PHASE3_TRIAL_OPERATION_GUIDE.md | 試験運用ガイド |

### Phase 3.5: 組織階層

| ファイル | 内容 |
|---------|------|
| 06_phase_3-5_org_hierarchy.md | 組織階層連携 |
| PHASE_3-5_DETAILED_DESIGN.md | 詳細設計 |
| PHASE_3-5_CHECKLIST.md | 実装チェックリスト |

### Phase 4: BPaaS

| ファイル | 内容 |
|---------|------|
| 08_phase_4_and_bpaas.md | Phase 4・BPaaS戦略 |

### Phase C: 会議系

| ファイル | 内容 |
|---------|------|
| 07_phase_c_meetings.md | 議事録自動化 |

### 組織論・フロントエンド

| ファイル | 内容 |
|---------|------|
| 11_organizational_theory_guidelines.md | 組織論的行動指針 |
| 12_org_chart_frontend_design.md | org-chartフロントエンド設計 |

### Phase全体

| ファイル | 内容 |
|---------|------|
| 02_phase_overview.md | Phase構成全体図 |

---

## アーカイブ

> **注意:** アーカイブ内のファイルは `ZZ_DEPRECATED_` プレフィックスが付いています。
> これはファイル一覧でアーカイブが最下部にソートされ、誤参照を防ぐためです。

### archive/legacy/（統合された旧設計書）

以下の設計書は `25_llm_native_brain_architecture.md` に統合されました。

| 旧ファイル | 統合先 |
|-----------|--------|
| 00_Goals_and_Principles.md | 25章 第3章 |
| 13_brain_architecture.md | 25章 第5-6章 |
| 14_brain_refactoring_plan.md | 25章 第12章 |
| 15_phase2d_ceo_learning.md | 25章 第6章 |
| 17_brain_completion_roadmap.md | 25章 第12章 |
| 18_phase2e_learning_foundation.md | 25章 第9章 |
| 19_ultimate_brain_architecture.md | 25章 第6章 |
| 20_next_generation_capabilities.md | 25章 付録 |
| 21_phase2l_execution_excellence.md | 25章 第6章 |
| 23_proactive_violation_analysis.md | 25章 第4章 |
| 24_polished_system_prompt.md | 25章 付録17.4 |
| brain_capability_integration_design.md | 25章 第6章 |

### archive/（その他アーカイブ）

| ファイル | 理由 |
|---------|------|
| 00_README.md（旧） | 本ファイルに置き換え |
| CHANGELOG.md | git logで参照可能 |
| 10_troubleshooting_and_faq.md | 実装時に動的生成 |
| 16_old_code_removal_plan.md | 実装完了済み |
| その他 | 一時的レポート等 |

---

## クイックリファレンス

### 「〇〇について知りたい」→「見るべきファイル」

| 知りたいこと | 見るファイル |
|-------------|-------------|
| 脳アーキテクチャの全体像 | 25章 第5章 |
| LLMがして良いこと/いけないこと | 25章 第4章（LLM Brain 憲法） |
| System Promptの詳細 | 25章 付録17.4 |
| データソース優先順位 | CLAUDE.md セクション3 |
| 権限レベル（6段階） | CLAUDE.md セクション7 |
| 10の鉄則 | CLAUDE.md セクション5 |
| DBスキーマ | 03_database_design.md |
| API仕様 | 04_api_and_security.md |
| 実装規約 | 09_implementation_standards.md |

---

## 変更履歴

| バージョン | 日付 | 変更内容 |
|-----------|------|---------|
| v1.0.0 | 2026-01-17 | 初版作成 |
| v2.0.0 | 2026-01-30 | 設計書リファクタリング（3層構造化、25章を主軸に統合） |

---

**このガイドについての質問は、CLAUDE.mdを参照してください。**
