# 設計書全体整合性レビュー提案書

**作成日:** 2026-02-01
**完了日:** 2026-02-02
**目的:** 「社長の分身・最高の秘書」という目的に対し、設計の安全性・拡張性・運用性を担保する
**ステータス:** ✅ 完了（全10課題修正済み）
**作成者:** Claude Code（経営参謀・SE・PM）

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | 設計書整合性レビューに基づく修正提案書（完了報告含む） |
| **書くこと** | 各課題の「問題→影響→修正案→完了状況」、優先順位 |
| **書かないこと** | 実装コードの詳細（各設計書を参照） |
| **SoT（この文書が正）** | 設計整合性課題の優先順位と修正方針 |
| **Owner** | カズさん（代表） |
| **更新トリガー** | 新たな課題発見時 |

---

## エグゼクティブサマリー

### 課題の全体像

| 重大度 | 件数 | 主な課題 |
|--------|------|---------|
| **High（重大）** | 4件 | RLS矛盾、Chain-of-Thought vs PII、DB設計重複、セキュリティ文言 |
| **Medium（中）** | 4件 | 同期APIリカバリ、会議録PII、tenant_id統一、Google Drive検証 |
| **Low（軽微）** | 2件 | 設計書導線、System Prompt反映確認 |

### 推奨対応順

1. **#2 Chain-of-Thought vs PII** ← 最優先（情報漏洩リスク直結）
2. **#3 DB設計SoT統一** ← 技術的負債解消（即座に対応可能）
3. **#1 RLS要件の明確化** ← Phase 3.5移行前に必要
4. **#4 セキュリティ文言の修正** ← 営業説明の正確性
5. 残りはMedium/Low順

---

## A. 重大（High）課題

---

### 課題 #1: RLSとPhase 3設計の矛盾

#### 問題

**CLAUDE.mdの規定（10の鉄則 #2）:**
> 「RLS（Row Level Security）を実装」

**05_phase3_knowledge_detailed_design.md 104行目の記載:**
> | 2 | RLS実装 | Phase 4Aで完全実装、Phase 3ではアプリレベルで制御 |

**security_and_bcp_guide.md 77行目の顧客向け説明:**
> | 技術名は？ | Row Level Security（RLS）といいます |

#### 矛盾の詳細

| 設計書 | 記載内容 | 問題点 |
|--------|---------|--------|
| CLAUDE.md | 「RLS必須」（10の鉄則） | 原則として明記されている |
| 05章 | 「Phase 4Aで完全実装」 | Phase 3では例外扱いになっている |
| security_and_bcp_guide.md | 「RLSで分離」と顧客説明 | 実際は未実装（顧客への誤説明） |
| RLS_POLICY_DESIGN.md | 詳細設計は存在 | 実装時期が「Phase 4A」 |

#### 放置すると何が起こるか

1. **情報漏洩リスク**: Phase 3時点ではアプリレベル制御のみ。開発者がWHERE句を忘れると他社データが見える
2. **顧客への誤説明**: 「RLSで完全分離」と説明しているが、実際は未実装。信用失墜のリスク
3. **設計書の信頼性低下**: 「必須」と書いてあるのに実装されていないと、他の鉄則も守られているか疑念が生じる

#### 修正案

**案A: Phase 3でRLSの最低限実装を追加（推奨）**

```markdown
# CLAUDE.mdへの追記案

## 10の鉄則 #2 の補足

| Phase | RLS実装レベル | 説明 |
|-------|-------------|------|
| Phase 3 | 最低限 | 主要テーブル（documents, document_chunks）にRLS適用 |
| Phase 3.5 | 中間 | 組織階層テーブル（departments等）にRLS適用 |
| Phase 4A | 完全 | 全テーブルにRLS適用 + 検証テスト完備 |

> **注意**: Phase 3でも「アプリレベル制御のみ」は禁止。最低限のRLSは必須。
```

**案B: 顧客説明の修正**

```markdown
# security_and_bcp_guide.md 77行目の修正案

| 質問 | 回答（現在） | 回答（修正後） |
|------|------------|--------------|
| どうやって分けてる？ | システム上、物理的に不可能な設計です | アプリケーションとデータベースの両方で二重チェックしています |
| 技術名は？ | Row Level Security（RLS）といいます | アプリケーションレベルでの厳格なアクセス制御を実施しています。データベースレベルのRLSは段階的に導入中です |
```

**案C: CLAUDE.md 10の鉄則 #2 の修正**

```markdown
# 10の鉄則 #2 の修正案

| # | 鉄則 | 説明（現在） | 説明（修正後） |
|---|------|------------|--------------|
| 2 | RLS実装 | やらないと他社のデータが見える | 段階的に実装。Phase 3ではアプリレベル + 主要テーブルのRLS必須、Phase 4Aで完全実装 |
```

#### 関連ファイル

| ファイル | 変更内容 |
|---------|---------|
| CLAUDE.md セクション5 | 10の鉄則 #2 に実装段階を明記 |
| 05_phase3_knowledge_detailed_design.md | 「最低限のRLS」を必須に変更 |
| security_and_bcp_guide.md | 顧客説明を正確な表現に修正 |
| RLS_POLICY_DESIGN.md | Phase 3向けの最低限ポリシーを追加 |

---

### 課題 #2: Chain-of-Thought必須出力とPII/監査の衝突

#### 問題

**25章 3.2節 201行目の規定:**
> | 8 | **思考過程の透明性** | Chain-of-Thoughtを必須化。全判断の理由を記録 |

**25章 4.2.2節 317行目:**
> │  │  ・思考過程の出力（Chain-of-Thought）              ✅ 必須    │

**25章 4.2.2節 383行目:**
> │  ・思考過程も自動記録                                                │

**CLAUDE.mdセクション8.3 監査ログのルール:**
> | 記録しない | 名前、メール、メッセージ本文（漏洩リスク防止） |

#### 矛盾の詳細

思考過程（Chain-of-Thought）には、以下のような個人情報が混入する可能性がある：

```
【思考過程の例】
「田中太郎さんの給与情報を確認したい」というリクエストを受けた。
田中さんは営業部の部長で、給与は月額85万円...
→ この思考過程をそのまま記録すると、監査ログのルールに違反
```

| 観点 | 25章の規定 | CLAUDE.mdの規定 | 矛盾 |
|------|-----------|----------------|------|
| 思考過程 | 全て記録 | - | - |
| 個人名 | - | 記録しない | ⚠️ 矛盾 |
| メール | - | 記録しない | ⚠️ 矛盾 |
| メッセージ本文 | - | 記録しない | ⚠️ 矛盾 |

#### 放置すると何が起こるか

1. **情報漏洩**: 思考過程に含まれる個人情報（名前、給与、評価等）がログに残り、漏洩リスク
2. **監査対応の困難**: 「思考過程を記録」と「個人情報を記録しない」が矛盾し、どちらを守るべきか不明確
3. **法的リスク**: 個人情報保護法違反のリスク（不必要な個人情報の保存）

#### 修正案

**案A: 思考過程のPIIマスキングルール追加（推奨）**

```markdown
# 25章への追記案（4.3.8節「思考過程の出力」の後に追加）

### 4.3.9 思考過程のPII除去（PII Sanitization）

| 項目 | 内容 |
|------|------|
| **定義** | 思考過程に含まれるPII（個人識別情報）を除去してから記録する |
| **適用タイミング** | Observability Layerで思考過程を記録する直前 |
| **処理方式** | マスキング（元データは復元不可能にする） |

#### 4.3.9.1 マスキング対象

| 対象 | マスキング後 | 例 |
|------|------------|-----|
| 個人名 | `[PERSON]` | 田中太郎 → [PERSON] |
| メールアドレス | `[EMAIL]` | tanaka@example.com → [EMAIL] |
| 電話番号 | `[PHONE]` | 090-1234-5678 → [PHONE] |
| 給与/金額（個人に紐づく） | `[AMOUNT]` | 月額85万円 → [AMOUNT] |
| 住所 | `[ADDRESS]` | 東京都渋谷区... → [ADDRESS] |
| 評価/査定情報 | `[EVALUATION]` | S評価 → [EVALUATION] |

#### 4.3.9.2 実装例

```python
import re

def sanitize_reasoning(reasoning: str) -> str:
    """思考過程からPIIを除去"""

    # 個人名パターン（日本語名）
    reasoning = re.sub(r'[一-龯ぁ-んァ-ン]{2,4}(さん|様|氏|部長|課長|社長)', '[PERSON]', reasoning)

    # メールアドレス
    reasoning = re.sub(r'[\w\.-]+@[\w\.-]+', '[EMAIL]', reasoning)

    # 電話番号
    reasoning = re.sub(r'\d{2,4}[-\s]?\d{2,4}[-\s]?\d{2,4}', '[PHONE]', reasoning)

    # 金額（給与等）
    reasoning = re.sub(r'(月額|年収|給与|報酬)[：:]*[\s]*\d+[万千]円?', r'\1[AMOUNT]', reasoning)

    return reasoning
```

#### 4.3.9.3 記録される形式

**マスキング前:**
```
田中太郎さんの給与情報を確認したい。田中さんは営業部の部長で、給与は月額85万円。
tanaka@soulsyncs.jp にメールを送信する必要がある。
```

**マスキング後（記録される形式）:**
```
[PERSON]の給与情報を確認したい。[PERSON]は営業部の部長で、給与は[AMOUNT]。
[EMAIL] にメールを送信する必要がある。
```
```

**案B: 思考過程の記録レベルを段階化**

```markdown
# 思考過程の記録レベル

| レベル | 記録内容 | 用途 |
|--------|---------|------|
| **要約のみ** | 「タスク作成を提案」等の要約 | 通常運用（推奨） |
| **詳細（マスキング済み）** | PIIをマスキングした思考過程 | デバッグ時 |
| **詳細（生データ）** | 思考過程そのまま | 禁止（PII漏洩リスク） |

デフォルト: 要約のみ
デバッグ時: 詳細（マスキング済み）
```

#### 関連ファイル

| ファイル | 変更内容 |
|---------|---------|
| 25章 4.3節 | 4.3.9「思考過程のPII除去」を追加 |
| CLAUDE.md セクション8 | PIIマスキングルールを明記 |
| lib/brain/observability.py | sanitize_reasoning()関数を実装 |
| OPERATIONS_RUNBOOK.md | PII漏洩時の対応手順を追加 |

---

### 課題 #3: DB設計SoTの重複（ドリフトリスク）

#### 問題

同じテーブル定義が複数の設計書に存在している：

| テーブル | 03章 | 06章 | 重複状況 |
|---------|------|------|---------|
| departments | ✅ 定義あり | ✅ 定義あり | 重複 |
| user_departments | ✅ 定義あり | ✅ 定義あり | 重複 |
| department_access_scopes | ✅ 定義あり | ✅ 定義あり | 重複 |

#### 具体的な重複箇所

**03_database_design.md（5.2.5節）:**
```sql
CREATE TABLE departments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50),
    ...
);
```

**06_phase_3-5_org_hierarchy.md（Week 7セクション）:**
```sql
CREATE TABLE departments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),  -- ⚠️ ON DELETE CASCADE が欠落
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50),
    ...
);
```

#### 放置すると何が起こるか

1. **スキーマ不整合**: 片方を更新しても、もう片方が古いままになる
2. **実装時の混乱**: どちらのスキーマを参照すべきか不明確
3. **本番障害**: マイグレーション時に異なるスキーマが適用され、外部キー制約等が欠落

#### 修正案

**案A: 03章をSoTとして一本化（推奨）**

```markdown
# 06_phase_3-5_org_hierarchy.md の修正案

## 変更前（現状）
Week 7セクションにCREATE TABLEの完全な定義

## 変更後
### ■ Week 7: データモデル構築

> **テーブル定義のSoT:** [03_database_design.md](03_database_design.md) セクション5.2.5
>
> 本設計書では実装手順のみを記載。テーブル定義は必ず03章を参照すること。

```python
async def upgrade():
    """組織階層テーブルを作成

    テーブル定義: docs/03_database_design.md セクション5.2.5
    """
    # LTREEエクステンションを有効化
    await conn.execute("CREATE EXTENSION IF NOT EXISTS ltree;")

    # 以下のテーブル作成SQLは03章の定義に準拠すること
    # ここでは参照のみ記載
```
```

**案B: DESIGN_COVERAGE_MATRIX.mdでの明示**

```markdown
# DESIGN_COVERAGE_MATRIX.md への追記案

## DB設計のSoTルール

| 設計要素 | SoT（正） | 参照のみ | 備考 |
|---------|----------|---------|------|
| departments テーブル | 03章 5.2.5 | 06章 Week 7 | 06章は手順書、定義は03章 |
| user_departments テーブル | 03章 5.2.5 | 06章 Week 7 | 同上 |
| department_access_scopes テーブル | 03章 5.2.5 | 06章 Week 7 | 同上 |

> **ルール**: テーブル定義を変更する場合は、必ず03章を更新すること。
> 06章等の手順書では「03章を参照」と記載するのみとし、CREATE TABLE文のコピーは禁止。
```

#### 関連ファイル

| ファイル | 変更内容 |
|---------|---------|
| 06_phase_3-5_org_hierarchy.md | CREATE TABLE文を削除し、03章への参照に変更 |
| DESIGN_COVERAGE_MATRIX.md | DB設計のSoTルールを追記 |
| PHASE_3-5_DETAILED_DESIGN.md | 同様に参照のみに変更 |

---

### 課題 #4: セキュリティ・BCP説明の事実整合性

#### 問題

**security_and_bcp_guide.md 31行目の表現:**
> 「ソウルくんは、日本政府も認めたGoogleのデータセンターで、銀行と同じレベルのセキュリティで守られています。」

#### 検証結果

| 表現 | 事実確認 | 評価 |
|------|---------|------|
| 「日本政府も認めた」 | ✅ 事実（ISMAP登録済み） | OK（ただし出典明記が望ましい） |
| 「銀行と同じレベル」 | ⚠️ 誤解を招く可能性 | 要修正（銀行は追加要件あり） |
| 「RLSで完全分離」 | ❌ 現時点では未実装 | 要修正（課題#1で対応） |

#### 放置すると何が起こるか

1. **顧客からのクレーム**: 「銀行と同じ」と言ったのに、銀行のセキュリティ監査では不合格になるケース
2. **営業担当の誤説明**: 根拠を知らずに説明し、詳しい顧客から突っ込まれる
3. **契約トラブル**: 説明と実態の乖離が発覚した場合、契約解除や損害賠償のリスク

#### 修正案

**案A: 出典の明記 + 表現の修正（推奨）**

```markdown
# security_and_bcp_guide.md の修正案

## 1. 結論（30秒で伝える版）の修正

**現在:**
> 「ソウルくんは、日本政府も認めたGoogleのデータセンターで、銀行と同じレベルのセキュリティで守られています。」

**修正後:**
> 「ソウルくんは、日本政府のISMAP認定を取得したGoogle Cloudで稼働しています。
> ISO 27001（国際セキュリティ規格）とSOC 2 Type II（第三者監査）を取得済みで、
> 大手企業と同等のセキュリティ基盤を使用しています。」

## 2. 出典セクションの追加

### 出典・根拠一覧

| 主張 | 根拠 | 出典URL | 確認日 |
|------|------|---------|--------|
| ISMAP登録済み | 政府情報システムのためのセキュリティ評価制度 | https://www.ismap.go.jp/csm | 2026-01-26 |
| ISO 27001取得 | Google Cloudの認証一覧 | https://cloud.google.com/security/compliance/iso-27001 | 2026-01-26 |
| SOC 2 Type II取得 | Google Cloudの認証一覧 | https://cloud.google.com/security/compliance/soc-2 | 2026-01-26 |
| 東京リージョン | asia-northeast1 | https://cloud.google.com/compute/docs/regions-zones | 2026-01-26 |

## 3. 四半期見直しフローの追加

### 見直しスケジュール

| 時期 | 確認事項 | 担当 |
|------|---------|------|
| 毎四半期末 | 認証・登録の有効性確認 | Tech Lead |
| 毎四半期末 | 表現と実装の整合性確認 | 営業 + Tech Lead |
| 認証更新時 | 出典URLの更新 | Tech Lead |

### 見直しチェックリスト

- [ ] ISMAP登録が有効か確認
- [ ] ISO 27001/SOC 2の有効期限を確認
- [ ] 「銀行と同じ」等の表現が実態と合っているか確認
- [ ] RLSの実装状況と説明が整合しているか確認
```

**案B: 「銀行と同じ」表現の削除**

```markdown
# 表現の修正

**削除する表現:**
- 「銀行と同じレベル」
- 「世界最高レベル」

**推奨表現:**
- 「ISO 27001認証を取得した基盤」
- 「ISMAP登録済みのクラウド」
- 「大手企業も採用している基盤」
```

#### 関連ファイル

| ファイル | 変更内容 |
|---------|---------|
| security_and_bcp_guide.md | 表現の修正 + 出典セクション追加 + 四半期見直しフロー追加 |
| DOCUMENTATION_FRESHNESS_POLICY.md | security_and_bcp_guide.mdの見直しルールを追加 |

---

## B. 中（Medium）課題

---

### 課題 #5: 組織図同期APIの破壊的フロー

#### 問題

**04_api_and_security.md 196-201行目の設計:**
```python
# 5. フルシンクの場合、既存データを削除
if data.sync_type == "full":
    await Department.filter(organization_id=org_id).delete()
    await UserDepartment.filter(
        user_id__organization_id=org_id
    ).delete()
```

#### 放置すると何が起こるか

1. **同期失敗時のデータ消失**: 削除後にエラーが発生すると、全データが消失
2. **タスク・権限の破壊**: 部署に紐づくタスクや権限設定が全て無効化
3. **復旧困難**: バックアップからの復旧しか手段がない

#### 修正案

**案A: Staged Commit方式（推奨）**

```markdown
# 04_api_and_security.md への追記案

### 5.5.2 組織図同期のリカバリ設計

#### Staged Commit方式

```python
async def sync_org_chart_staged(org_id: str, data: OrgChartSyncRequest):
    """Staged Commit方式での組織図同期

    1. 新データを別テーブルに準備
    2. 検証が全てパスしたら、アトミックに切り替え
    3. 失敗時は旧データがそのまま残る
    """

    # 1. ステージングテーブルに新データを作成
    staging_id = await create_staging_tables(org_id, data)

    try:
        # 2. ステージングデータの検証
        await validate_staging_data(staging_id)

        # 3. 依存関係の検証（タスク、権限等）
        await validate_dependencies(org_id, staging_id)

        # 4. アトミックに切り替え（rename方式）
        async with db.transaction():
            await rename_table(f"departments_{org_id}", f"departments_{org_id}_backup")
            await rename_table(f"departments_{org_id}_staging", f"departments_{org_id}")

        # 5. バックアップを削除（成功確認後）
        await drop_backup_tables(org_id)

    except Exception as e:
        # 失敗時はステージングを削除、旧データは維持
        await drop_staging_tables(staging_id)
        raise
```

#### リカバリ手順

| シナリオ | 検出方法 | 復旧手順 | RTO |
|---------|---------|---------|-----|
| 同期中にエラー | トランザクションロールバック | 自動復旧（旧データ維持） | 0分 |
| 同期完了後に問題発覚 | 手動検出 | バックアップテーブルからリストア | 5分 |
| バックアップもない | 監査ログ | 前日バックアップから復元 | 1時間 |

#### バックアップ保持期間

| データ | 保持期間 | 理由 |
|--------|---------|------|
| 同期前バックアップ | 24時間 | 当日中の問題検出用 |
| 日次バックアップ | 7日 | 週単位での問題検出用 |
```

**案B: 差分同期のみ許可**

```markdown
# sync_type の制限

| sync_type | 許可 | 理由 |
|-----------|------|------|
| `full` | ❌ 禁止 | データ消失リスク |
| `incremental` | ✅ 許可 | 差分のみ適用 |
| `upsert` | ✅ 許可 | 存在すれば更新、なければ作成 |

> **注意**: 既存の `sync_type=full` を使用しているAPIは、`sync_type=recreate_staged` に変更する。
```

#### 関連ファイル

| ファイル | 変更内容 |
|---------|---------|
| 04_api_and_security.md | Staged Commit方式 + リカバリ手順を追加 |
| OPERATIONS_RUNBOOK.md | 組織図同期失敗時の復旧手順を追加 |

---

### 課題 #6: 会議録（Phase C）のPII/保存ルール不足

#### 問題

**07_phase_c_meetings.md の現状:**
- Whisper API/GPT-4の利用は記載あり
- 録画データの同意/保存期間/削除手順/閲覧権限の規定が不明確
- 「Addendum v1.1を参照」との記載があるが、Addendumの場所が不明確

#### 放置すると何が起こるか

1. **プライバシー事故**: 同意なしに会議を録音・文字起こしし、社内反発
2. **法的リスク**: 個人情報保護法違反（目的外利用、保存期間超過）
3. **社内反発**: 「監視されている」という不信感

#### 修正案

**案A: PII/保存ルールの明文化（推奨）**

```markdown
# 07_phase_c_meetings.md への追記案

## 10. プライバシー・PII保護設計

### 10.1 同意取得

| 対象 | 同意方法 | タイミング |
|------|---------|-----------|
| 会議主催者 | 会議設定時に同意チェックボックス | 会議作成時 |
| 会議参加者 | 会議開始時に「録音します」の自動通知 | 会議開始時 |
| 外部参加者 | 録音前に明示的な同意確認 | 録音開始前 |

### 10.2 保存期間

| データ種類 | 保存期間 | 削除方法 | 根拠 |
|-----------|---------|---------|------|
| 録画ファイル | 90日 | 自動削除ジョブ | 議事録作成後は不要 |
| 文字起こし（生データ） | 90日 | 自動削除ジョブ | 議事録で代替可能 |
| 議事録（要約） | 3年 | 手動削除 | 業務記録として保持 |
| アクションアイテム | 完了後1年 | 手動削除 | タスク管理として保持 |

### 10.3 閲覧権限

| データ種類 | 閲覧可能者 | 根拠 |
|-----------|-----------|------|
| 録画ファイル | 会議参加者のみ | プライバシー保護 |
| 文字起こし | 会議参加者のみ | プライバシー保護 |
| 議事録 | 会議参加者 + 上長 | 業務上の必要性 |
| アクションアイテム | タスク担当者 + 関係者 | タスク管理の必要性 |

### 10.4 PII除去

| 対象 | 除去方法 | 例 |
|------|---------|-----|
| 議事録内の個人名 | 役職に置換 | 「田中さん」→「営業部長」 |
| 連絡先 | マスキング | 090-xxxx-xxxx |
| 機密数値 | マスキング | 売上○○円 → 売上[非公開] |

### 10.5 削除手順

```python
async def delete_meeting_data(meeting_id: str, reason: str):
    """会議データの削除

    Args:
        meeting_id: 会議ID
        reason: 削除理由（監査ログ用）
    """
    # 1. 監査ログに削除予告を記録
    await audit_log.create(
        action="meeting_data_delete_scheduled",
        meeting_id=meeting_id,
        reason=reason
    )

    # 2. 録画ファイルを削除
    await gcs.delete(f"meetings/{meeting_id}/recording.mp4")

    # 3. 文字起こしデータを削除
    await db.meeting_transcripts.delete(meeting_id=meeting_id)

    # 4. 監査ログに削除完了を記録
    await audit_log.create(
        action="meeting_data_deleted",
        meeting_id=meeting_id
    )
```
```

#### 関連ファイル

| ファイル | 変更内容 |
|---------|---------|
| 07_phase_c_meetings.md | プライバシー・PII保護設計セクションを追加 |
| OPERATIONS_RUNBOOK.md | 会議データ削除手順を追加 |

---

### 課題 #7: organization_id / tenant_id 同義の影響範囲が曖昧

#### 問題

**01_philosophy_and_principles.md 102行目:**
> | **7** | **テナント識別子の一元管理**【v10.1追加】 | tenant_id = organization_id（同義）。Phase 4Aでorganization_idに統一予定 |

#### 現状の問題

| ファイル | 使用している識別子 | 問題点 |
|---------|------------------|--------|
| 既存コード | tenant_id | 古い命名 |
| 新規設計書 | organization_id | 新しい命名 |
| 07_phase_c_meetings.md | tenant_id/organization_id 混在 | どちらを使うべきか不明確 |

#### 放置すると何が起こるか

1. **実装の混乱**: 開発者がどちらを使うべきか迷う
2. **データ不整合**: 片方のIDでフィルタしてもう片方のデータが漏れる
3. **移行時のトラブル**: Phase 4Aでの統一時にマッピング漏れ

#### 修正案

**案A: 移行ガイドラインの明文化（推奨）**

```markdown
# 01_philosophy_and_principles.md への追記案

## 1.5 テナント識別子の移行ガイドライン【v10.1追加】

### 用語の統一

| 用語 | 定義 | 使用場所 |
|------|------|---------|
| `organization_id` | **正式名称**。今後はこちらを使用 | 新規コード、設計書 |
| `tenant_id` | **旧名称**。organization_idと同義 | 既存コード（Phase 4Aで廃止予定） |

### 新規開発時のルール

| 場面 | ルール |
|------|--------|
| 新規テーブル作成 | `organization_id` を使用（tenant_id は禁止） |
| 新規API作成 | `organization_id` を使用 |
| 既存コード修正 | 可能であれば `organization_id` に置換 |
| 設計書作成 | `organization_id` を使用 |

### 移行計画

| Phase | 内容 | 時期 |
|-------|------|------|
| 現在 | 新規コードは`organization_id`、既存コードは`tenant_id`のまま | - |
| Phase 4A | 全コードを`organization_id`に統一 | Q3 |
| Phase 4A完了後 | `tenant_id`を完全廃止 | Q4 |

### 移行時の検証チェックリスト

- [ ] 全テーブルで`organization_id`が使用されているか
- [ ] 全APIで`organization_id`が使用されているか
- [ ] 全設計書で`organization_id`が使用されているか
- [ ] `tenant_id`への参照が残っていないか（grep検索）
```

#### 関連ファイル

| ファイル | 変更内容 |
|---------|---------|
| 01_philosophy_and_principles.md | 移行ガイドラインを追加 |
| CLAUDE.md | 用語統一のルールを追記 |
| 09_implementation_standards.md | コーディング規約に追記 |

---

### 課題 #8: Google Drive連携の誤配置リスク

#### 問題

**06_phase3_google_drive_integration.md の設計:**
- フォルダ構造 = 権限という設計
- 誤配置時の検証ジョブが未定義

#### 放置すると何が起こるか

1. **機密漏洩**: confidential資料を「全社共有」フォルダに入れると、全社員が閲覧可能に
2. **検出困難**: 誤配置を検出する仕組みがないと、漏洩に気づかない
3. **監査不能**: 誰がいつ誤配置したか追跡できない

#### 修正案

**案A: 検証ジョブ + 誤配置アラートの追加（推奨）**

```markdown
# 06_phase3_google_drive_integration.md への追記案

## 11. 誤配置検知・アラート設計

### 11.1 誤配置検知ジョブ

| 項目 | 内容 |
|------|------|
| **実行頻度** | 1時間ごと |
| **検知対象** | 機密区分と配置フォルダの不整合 |
| **アラート先** | 管理者Slack + メール |

#### 検知ルール

| ルール | 検知条件 | 重大度 |
|--------|---------|--------|
| 機密ファイルの公開フォルダ配置 | classification=confidential && folder=public | 🔴 Critical |
| 部署限定ファイルの他部署配置 | department_id != folder_department_id | 🟠 High |
| 経営陣限定ファイルの一般配置 | classification=restricted && folder!=restricted | 🔴 Critical |

#### 検知ロジック

```python
async def detect_misplaced_documents():
    """誤配置ドキュメントを検知"""

    misplaced = []

    # 全ドキュメントを走査
    documents = await db.documents.filter(is_active=True).all()

    for doc in documents:
        folder_classification = get_folder_classification(doc.google_drive_folder_id)

        # ルール1: 機密ファイルが公開フォルダにある
        if doc.classification == "confidential" and folder_classification == "public":
            misplaced.append({
                "doc_id": doc.id,
                "severity": "critical",
                "reason": "機密ファイルが公開フォルダに配置されています"
            })

        # ルール2: 部署限定ファイルが他部署にある
        if doc.department_id and doc.department_id != get_folder_department(doc.google_drive_folder_id):
            misplaced.append({
                "doc_id": doc.id,
                "severity": "high",
                "reason": "部署限定ファイルが他部署フォルダに配置されています"
            })

    return misplaced

async def send_misplacement_alert(misplaced: list):
    """誤配置アラートを送信"""

    if not misplaced:
        return

    critical = [m for m in misplaced if m["severity"] == "critical"]

    if critical:
        # Criticalは即座にアラート
        await slack.send("#security-alerts", f"🔴 機密ファイル誤配置検出: {len(critical)}件")
        await email.send("security@soulsyncs.jp", "緊急: 機密ファイル誤配置", critical)
    else:
        # High以下は日次サマリー
        await slack.send("#admin", f"⚠️ ファイル配置確認: {len(misplaced)}件")
```

### 11.2 監査ログ強化

| イベント | 記録内容 | 保持期間 |
|---------|---------|---------|
| ファイル配置 | folder_id, classification, user_id | 1年 |
| ファイル移動 | old_folder, new_folder, user_id | 1年 |
| 誤配置検出 | doc_id, reason, detected_at | 1年 |
| 誤配置修正 | doc_id, corrected_by, corrected_at | 1年 |
```

#### 関連ファイル

| ファイル | 変更内容 |
|---------|---------|
| 06_phase3_google_drive_integration.md | 誤配置検知・アラート設計セクションを追加 |
| OPERATIONS_RUNBOOK.md | 誤配置対応手順を追加 |

---

## C. 軽微（Low）課題

---

### 課題 #9: 設計書参照導線の長さ

#### 問題

設計書が多く（30+ファイル）、どこから見ればいいか迷いやすい。

#### 修正案

```markdown
# 00_README.md への追記案

## クイックスタート：最短参照ルート

### 「〇〇したい」→「見るファイル」

| やりたいこと | 見るファイル | 参照セクション |
|-------------|-------------|--------------|
| 全体の設計思想を理解したい | CLAUDE.md | 全体 |
| 脳の設計を理解したい | 25章 | 第4章（LLM Brain憲法） |
| DBテーブルを追加したい | 03章 | 該当セクション |
| APIを追加したい | 04章 | 該当セクション |
| 本番障害に対応したい | OPERATIONS_RUNBOOK.md | 該当セクション |
| 新機能を設計したい | FEATURE_ADDITION_FRAMEWORK.md | 全体 |

### 階層図

```
迷ったらまずここ
↓
CLAUDE.md（判断基準）
↓
何について？
├─ 脳 → 25章
├─ DB → 03章
├─ API → 04章
├─ 運用 → OPERATIONS_RUNBOOK.md
└─ 機能 → 該当Phase設計書
```
```

#### 関連ファイル

| ファイル | 変更内容 |
|---------|---------|
| 00_README.md | クイックスタートセクションを追加 |

---

### 課題 #10: Phase 2C/2.5とSystem Promptの反映確認不足

#### 問題

- Phase 2C/2.5の価値観・伴走方針がSystem Prompt v2.0に確実に反映されているか曖昧
- 「社長の分身」としての人格がブレるリスク

#### 修正案

```markdown
# 25章 付録への追記案

## 17.5 System Prompt反映チェックリスト

### Phase 2.5（目標達成支援）からの反映項目

| 項目 | 設計書の記載 | System Promptへの反映 | 確認 |
|------|------------|-------------------|------|
| 3つの設計原則 | 05_phase2-5 セクション1.2 | 「習慣化 > 機能」等をプロンプトに明記 | □ |
| 問い > 指示 | 05_phase2-5 セクション1.2 | 「問いかけスタイル」をプロンプトに明記 | □ |
| 伴走 > 監視 | 05_phase2-5 セクション1.2 | 「見守りスタイル」をプロンプトに明記 | □ |

### Phase 2C（MVV連携）からの反映項目

| 項目 | 設計書の記載 | System Promptへの反映 | 確認 |
|------|------------|-------------------|------|
| MVV自然な織り込み | 10_phase2c セクション2.2 | 「押し付けがましくなく」をプロンプトに明記 | □ |
| ベテラン秘書の姿勢 | 10_phase2c セクション1.1 | 「自ら気づいて提案」をプロンプトに明記 | □ |

### 更新ルール

| トリガー | アクション |
|---------|-----------|
| Phase 2C/2.5の設計変更 | System Prompt v2.0を更新 + チェックリスト確認 |
| System Promptの変更 | Phase設計書との整合性を確認 |
| 四半期レビュー | 全チェックリストを再確認 |
```

#### 関連ファイル

| ファイル | 変更内容 |
|---------|---------|
| 25章 付録 | 17.5 System Prompt反映チェックリストを追加 |
| 05_phase2-5_goal_achievement.md | System Promptへの反映要件を明記 |
| 10_phase2c_mvv_secretary.md | System Promptへの反映要件を明記 |

---

## 優先順位まとめ

### 対応順序（推奨）

| 順位 | 課題 | 重大度 | 理由 |
|------|------|--------|------|
| 1 | #2 Chain-of-Thought vs PII | High | 情報漏洩リスク直結。実装時に即座に問題化 |
| 2 | #3 DB設計SoT統一 | High | 技術的負債。即座に修正可能 |
| 3 | #1 RLS要件明確化 | High | 顧客説明との整合性。Phase 3.5前に必要 |
| 4 | #4 セキュリティ文言修正 | High | 営業説明の正確性。顧客信頼に直結 |
| 5 | #5 同期APIリカバリ | Medium | 本番運用前に必要 |
| 6 | #7 tenant_id統一 | Medium | Phase 4A移行準備 |
| 7 | #6 会議録PII | Medium | Phase C実装前に必要 |
| 8 | #8 Google Drive検証 | Medium | Phase 3本番運用前に必要 |
| 9 | #9 設計書導線 | Low | 開発効率向上 |
| 10 | #10 System Prompt反映 | Low | 品質向上 |

---

## 承認依頼

本提案書の内容について、以下の承認をお願いいたします。

- [ ] 全10課題の修正方針を承認
- [ ] 優先順位の変更があれば指示
- [ ] 追加で検討すべき課題があれば指示

**承認後、各課題の修正を順次実施いたします。**

---

## 更新履歴

| 日付 | 変更内容 |
|------|---------|
| 2026-02-01 | 初版作成（全10課題の提案） |

---

**このファイルについての質問は、カズさんに連絡してください。**
