"""
提案管理ハンドラー

main.pyから分割された知識提案の管理機能を提供する。

分割元: chatwork-webhook/main.py
分割日: 2026-01-25
バージョン: v10.24.2
"""

import json
import traceback
import httpx
import sqlalchemy
from typing import Optional, Dict, Any, List, Tuple, Callable


class ProposalHandler:
    """
    知識提案の管理を行うハンドラークラス

    外部依存を注入することで、main.pyとの疎結合を実現。

    v10.25.0: save_person_attribute依存を追加（人物情報提案対応）
    """

    def __init__(
        self,
        get_pool: Callable,
        get_secret: Callable,
        admin_room_id: str,
        admin_account_id: str,
        is_admin: Callable[[str], bool],
        save_person_attribute: Callable[[str, str, str, str], bool] = None,
        organization_id: str = "org_soulsyncs",
    ):
        """
        Args:
            get_pool: DB接続プールを取得する関数
            get_secret: Secret Managerから秘密情報を取得する関数
            admin_room_id: 管理部ルームID
            admin_account_id: 管理者アカウントID
            is_admin: 管理者判定関数
            save_person_attribute: 人物属性保存関数（v10.25.0追加）
            organization_id: 組織ID（Phase 4: テナント分離）
        """
        self.get_pool = get_pool
        self.get_secret = get_secret
        self.admin_room_id = admin_room_id
        self.admin_account_id = admin_account_id
        self.is_admin = is_admin
        self.save_person_attribute = save_person_attribute
        self.organization_id = organization_id

    def create_proposal(
        self,
        proposed_by_account_id: str,
        proposed_by_name: str,
        proposed_in_room_id: str,
        category: str,
        key: str,
        value: str,
        message_id: str = None
    ) -> Optional[int]:
        """
        知識の提案を作成

        Args:
            proposed_by_account_id: 提案者のアカウントID
            proposed_by_name: 提案者の名前
            proposed_in_room_id: 提案が行われたルームID
            category: 提案のカテゴリ
            key: 知識のキー
            value: 知識の値
            message_id: 関連するメッセージID

        Returns:
            作成された提案のID、またはエラー時はNone
        """
        try:
            pool = self.get_pool()
            with pool.begin() as conn:
                result = conn.execute(sqlalchemy.text("""
                    INSERT INTO knowledge_proposals
                    (organization_id, proposed_by_account_id, proposed_by_name, proposed_in_room_id,
                     category, key, value, message_id, status)
                    VALUES (:org_id, :account_id, :name, :room_id, :category, :key, :value, :message_id, 'pending')
                    RETURNING id
                """), {
                    "org_id": self.organization_id,
                    "account_id": proposed_by_account_id,
                    "name": proposed_by_name,
                    "room_id": proposed_in_room_id,
                    "category": category,
                    "key": key,
                    "value": value,
                    "message_id": message_id
                })
                proposal_id = result.fetchone()[0]
            print(f"✅ 提案を作成: ID={proposal_id}, {key}={value}")
            return proposal_id
        except Exception as e:
            print(f"❌ 提案作成エラー: {e}")
            traceback.print_exc()
            return None

    def get_pending_proposals(self) -> List[Dict]:
        """
        承認待ちの提案を取得

        v6.9.1: 古い順（FIFO）に変更 - 待たせている人から処理

        Returns:
            提案のリスト
        """
        try:
            pool = self.get_pool()
            with pool.connect() as conn:
                result = conn.execute(sqlalchemy.text("""
                    SELECT id, proposed_by_account_id, proposed_by_name, proposed_in_room_id,
                           category, key, value, message_id, created_at
                    FROM knowledge_proposals
                    WHERE organization_id = :org_id AND status = 'pending'
                    ORDER BY created_at ASC
                """), {"org_id": self.organization_id})
                rows = result.fetchall()
                return [{
                    "id": r[0], "proposed_by_account_id": r[1], "proposed_by_name": r[2],
                    "proposed_in_room_id": r[3], "category": r[4], "key": r[5],
                    "value": r[6], "message_id": r[7], "created_at": r[8]
                } for r in rows]
        except Exception as e:
            print(f"❌ 提案取得エラー: {e}")
            traceback.print_exc()
            return []

    def get_oldest_pending_proposal(self) -> Optional[Dict]:
        """
        最も古い承認待ち提案を取得（v6.9.1: FIFO）

        Returns:
            最も古い提案、またはNone
        """
        proposals = self.get_pending_proposals()
        return proposals[0] if proposals else None

    def get_latest_pending_proposal(self) -> Optional[Dict]:
        """
        最新の承認待ち提案を取得（後方互換性のため残す）

        Returns:
            最新の提案、またはNone
        """
        return self.get_oldest_pending_proposal()

    def get_proposal_by_id(self, proposal_id: int) -> Optional[Dict]:
        """
        ID指定で提案を取得（v6.9.1追加）

        Args:
            proposal_id: 提案ID

        Returns:
            提案データ、またはNone
        """
        try:
            pool = self.get_pool()
            with pool.connect() as conn:
                result = conn.execute(sqlalchemy.text("""
                    SELECT id, proposed_by_account_id, proposed_by_name, proposed_in_room_id,
                           category, key, value, message_id, created_at, status
                    FROM knowledge_proposals
                    WHERE organization_id = :org_id AND id = :id
                """), {"org_id": self.organization_id, "id": proposal_id})
                row = result.fetchone()
                if row:
                    return {
                        "id": row[0], "proposed_by_account_id": row[1], "proposed_by_name": row[2],
                        "proposed_in_room_id": row[3], "category": row[4], "key": row[5],
                        "value": row[6], "message_id": row[7], "created_at": row[8], "status": row[9]
                    }
                return None
        except Exception as e:
            print(f"❌ 提案取得エラー: {e}")
            traceback.print_exc()
            return None

    def get_unnotified_proposals(self) -> List[Dict]:
        """
        通知失敗した提案を取得（admin_notified=FALSE）

        v6.9.2追加

        Returns:
            未通知提案のリスト
        """
        try:
            pool = self.get_pool()
            with pool.connect() as conn:
                result = conn.execute(sqlalchemy.text("""
                    SELECT id, proposed_by_account_id, proposed_by_name, proposed_in_room_id,
                           category, key, value, message_id, created_at
                    FROM knowledge_proposals
                    WHERE organization_id = :org_id AND status = 'pending' AND admin_notified = FALSE
                    ORDER BY created_at ASC
                """), {"org_id": self.organization_id})
                rows = result.fetchall()
                return [{
                    "id": r[0], "proposed_by_account_id": r[1], "proposed_by_name": r[2],
                    "proposed_in_room_id": r[3], "category": r[4], "key": r[5],
                    "value": r[6], "message_id": r[7], "created_at": r[8]
                } for r in rows]
        except Exception as e:
            print(f"❌ 未通知提案取得エラー: {e}")
            traceback.print_exc()
            return []

    def approve_proposal(self, proposal_id: int, reviewed_by: str) -> bool:
        """
        提案を承認して知識または人物情報に反映

        v10.25.0: category='memory'の場合は人物情報として保存

        Args:
            proposal_id: 提案ID
            reviewed_by: 承認者のアカウントID

        Returns:
            成功時True
        """
        try:
            pool = self.get_pool()
            with pool.begin() as conn:
                # 提案を取得
                result = conn.execute(sqlalchemy.text("""
                    SELECT category, key, value, proposed_by_account_id
                    FROM knowledge_proposals WHERE organization_id = :org_id AND id = :id AND status = 'pending'
                """), {"org_id": self.organization_id, "id": proposal_id})
                row = result.fetchone()

                if not row:
                    print(f"⚠️ 提案ID={proposal_id}が見つからないか、既に処理済み")
                    return False

                category, key, value, proposed_by = row

                # v10.25.0: カテゴリに応じて保存先を分岐
                if category == 'memory':
                    # 人物情報の場合
                    if self.save_person_attribute:
                        try:
                            data = json.loads(value)
                            person_name = key
                            attr_type = data.get('type', 'その他')
                            attr_value = data.get('value', value)
                            self.save_person_attribute(person_name, attr_type, attr_value, 'proposal')
                            print(f"✅ 人物情報を保存: {person_name}の{attr_type}={attr_value}")
                        except json.JSONDecodeError:
                            # JSONパース失敗時はそのまま保存
                            self.save_person_attribute(key, 'その他', value, 'proposal')
                            print(f"⚠️ JSONパース失敗、そのまま保存: {key}={value}")
                    else:
                        print(f"⚠️ save_person_attributeが未設定のため、人物情報を保存できません")
                        return False
                else:
                    # 通常の知識の場合（Phase 4: org_idカラム対応）
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
                        "created_by": proposed_by
                    })

                # 提案を承認済みに更新
                conn.execute(sqlalchemy.text("""
                    UPDATE knowledge_proposals
                    SET status = 'approved', reviewed_by = :reviewed_by, reviewed_at = CURRENT_TIMESTAMP
                    WHERE organization_id = :org_id AND id = :id
                """), {"org_id": self.organization_id, "id": proposal_id, "reviewed_by": reviewed_by})

            print(f"✅ 提案ID={proposal_id}を承認: {key}={value}")
            return True
        except Exception as e:
            print(f"❌ 提案承認エラー: {e}")
            traceback.print_exc()
            return False

    def reject_proposal(self, proposal_id: int, reviewed_by: str) -> bool:
        """
        提案を却下

        Args:
            proposal_id: 提案ID
            reviewed_by: 却下者のアカウントID

        Returns:
            成功時True
        """
        try:
            pool = self.get_pool()
            with pool.begin() as conn:
                conn.execute(sqlalchemy.text("""
                    UPDATE knowledge_proposals
                    SET status = 'rejected', reviewed_by = :reviewed_by, reviewed_at = CURRENT_TIMESTAMP
                    WHERE organization_id = :org_id AND id = :id AND status = 'pending'
                """), {"org_id": self.organization_id, "id": proposal_id, "reviewed_by": reviewed_by})
            print(f"✅ 提案ID={proposal_id}を却下")
            return True
        except Exception as e:
            print(f"❌ 提案却下エラー: {e}")
            traceback.print_exc()
            return False

    def report_proposal_to_admin(
        self,
        proposal_id: int,
        proposer_name: str,
        key: str,
        value: str,
        category: str = None
    ) -> bool:
        """
        提案を管理部に報告

        v6.9.1: ID表示、admin_notifiedフラグ更新
        v10.25.0: category='memory'の場合は人物情報用メッセージ

        Args:
            proposal_id: 提案ID
            proposer_name: 提案者の名前
            key: 提案のキー
            value: 提案の値
            category: 提案のカテゴリ（v10.25.0追加）

        Returns:
            成功時True
        """
        try:
            chatwork_api_token = self.get_secret("SOULKUN_CHATWORK_TOKEN")

            # v10.25.0: カテゴリに応じてメッセージを変更
            if category == 'memory':
                # 人物情報の場合
                try:
                    data = json.loads(value)
                    attr_type = data.get('type', 'その他')
                    attr_value = data.get('value', value)
                    content_display = f"{key}さんの{attr_type}：{attr_value}"
                except json.JSONDecodeError:
                    content_display = f"{key}さんの情報：{value}"

                message = f"""📝 人物情報の登録提案があったウル！🐺

**提案ID:** {proposal_id}
**提案者:** {proposer_name}さん
**内容:** 「{content_display}」

ソウルくんが会社として問題ないか確認するウル！

・「承認 {proposal_id}」→ 覚えるウル
・「却下 {proposal_id}」→ 見送るウル
・「承認待ち一覧」→ 全ての提案を確認"""
            else:
                # 通常の知識の場合
                message = f"""📝 知識の更新提案があったウル！🐺

**提案ID:** {proposal_id}
**提案者:** {proposer_name}さん
**内容:** 「{key}: {value}」

ソウルくんが会社として問題ないか確認するウル！

・「承認 {proposal_id}」→ 反映するウル
・「却下 {proposal_id}」→ 見送るウル
・「承認待ち一覧」→ 全ての提案を確認"""

            url = f"https://api.chatwork.com/v2/rooms/{self.admin_room_id}/messages"
            headers = {"X-ChatWorkToken": chatwork_api_token}
            data = {"body": message}

            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, headers=headers, data=data)
                if response.status_code == 200:
                    print(f"✅ 管理部に提案を報告: proposal_id={proposal_id}")
                    # v6.9.1: 通知成功フラグを更新
                    try:
                        pool = self.get_pool()
                        with pool.begin() as conn:
                            conn.execute(sqlalchemy.text("""
                                UPDATE knowledge_proposals
                                SET admin_notified = TRUE
                                WHERE organization_id = :org_id AND id = :id
                            """), {"org_id": self.organization_id, "id": proposal_id})
                    except Exception as e:
                        print(f"⚠️ admin_notified更新エラー: {e}")
                    return True
                else:
                    print(f"⚠️ 管理部への報告エラー: {response.status_code} - {response.text}")
                    return False
        except Exception as e:
            print(f"❌ 管理部への報告エラー: {e}")
            traceback.print_exc()
            return False

    def notify_proposal_result(self, proposal: Dict, approved: bool) -> None:
        """
        提案の結果を提案者に通知

        v10.25.0: category='memory'の場合は人物情報用メッセージ

        Args:
            proposal: 提案データ
            approved: 承認された場合True
        """
        try:
            chatwork_api_token = self.get_secret("SOULKUN_CHATWORK_TOKEN")
            room_id = proposal.get("proposed_in_room_id")

            if not room_id:
                print("⚠️ 提案元ルームIDが不明")
                return

            category = proposal.get("category", "")
            key = proposal.get("key", "")
            value = proposal.get("value", "")

            # v10.25.0: カテゴリに応じてメッセージを変更
            if category == 'memory':
                # 人物情報の場合
                try:
                    data = json.loads(value)
                    attr_type = data.get('type', 'その他')
                    attr_value = data.get('value', value)
                    content_display = f"{key}さんの{attr_type}「{attr_value}」"
                except json.JSONDecodeError:
                    content_display = f"{key}さんの情報「{value}」"

                if approved:
                    message = f"""✅ 人物情報の登録が承認されたウル！🐺✨

{content_display}を覚えたウル！
教えてくれてありがとウル！"""
                else:
                    message = f"""🙏 人物情報の登録は今回は見送りになったウル

{content_display}は登録しなかったウル。
また何かあれば教えてウル！🐺"""
            else:
                # 通常の知識の場合
                if approved:
                    message = f"""✅ 提案が承認されたウル！🐺✨

「{key}: {value}」を覚えたウル！
教えてくれてありがとウル！"""
                else:
                    message = f"""🙏 提案は今回は見送りになったウル

「{key}: {value}」は反映しなかったウル。
また何かあれば教えてウル！🐺"""

            url = f"https://api.chatwork.com/v2/rooms/{room_id}/messages"
            headers = {"X-ChatWorkToken": chatwork_api_token}
            data = {"body": message}

            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, headers=headers, data=data)
                if response.status_code == 200:
                    print(f"✅ 提案者に結果を通知")
                else:
                    print(f"⚠️ 提案者への通知エラー: {response.status_code}")
        except Exception as e:
            print(f"❌ 提案者への通知エラー: {e}")
            traceback.print_exc()

    def retry_proposal_notification(self, proposal_id: int) -> Tuple[bool, str]:
        """
        提案の通知を再送（v6.9.2追加）

        v10.25.0: category対応

        Args:
            proposal_id: 提案ID

        Returns:
            (成功フラグ, メッセージ)
        """
        proposal = self.get_proposal_by_id(proposal_id)
        if not proposal:
            return False, f"提案ID={proposal_id}が見つからない"

        if proposal["status"] != "pending":
            return False, f"提案ID={proposal_id}は既に処理済み（{proposal['status']}）"

        # 再通知を実行
        success = self.report_proposal_to_admin(
            proposal_id,
            proposal["proposed_by_name"],
            proposal["key"],
            proposal["value"],
            proposal.get("category")  # v10.25.0: カテゴリを渡す
        )

        if success:
            return True, f"提案ID={proposal_id}を再通知した"
        else:
            return False, f"提案ID={proposal_id}の再通知に失敗"

    def handle_proposal_decision(
        self,
        params: Dict,
        room_id: str,
        account_id: str,
        sender_name: str,
        context: Any = None
    ) -> Optional[str]:
        """
        提案の承認/却下を処理するハンドラー（AI司令塔経由）

        - 管理者のみ有効
        - 管理部ルームでの発言のみ対応
        v6.9.1: ID指定方式を推奨（handle_proposal_by_idを使用）

        Args:
            params: パラメータ
            room_id: ルームID
            account_id: アカウントID
            sender_name: 発言者の名前
            context: コンテキスト

        Returns:
            応答メッセージ、またはNone
        """
        decision = params.get("decision", "").lower()

        # 管理部ルームかチェック
        if str(room_id) != str(self.admin_room_id):
            # 管理部以外での「承認」「却下」は無視（一般会話として処理）
            return None

        # 最新の承認待ち提案を取得
        proposal = self.get_latest_pending_proposal()

        if not proposal:
            return "🤔 承認待ちの提案は今ないウル！"

        # 管理者判定
        if self.is_admin(account_id):
            # 管理者による承認/却下
            if decision == "approve" or decision in ["承認", "ok", "いいよ", "反映して", "おけ"]:
                if self.approve_proposal(proposal["id"], str(account_id)):
                    # 提案者に通知
                    try:
                        self.notify_proposal_result(proposal, approved=True)
                    except Exception as e:
                        print(f"⚠️ 提案者への通知エラー: {e}")

                    return f"✅ 承認したウル！🐺\n\n「{proposal['key']}: {proposal['value']}」を覚えたウル！\n{proposal['proposed_by_name']}さんにも伝えておくウル！"
                else:
                    return "😢 承認処理でエラーが起きたウル..."

            elif decision == "reject" or decision in ["却下", "だめ", "やめて", "いらない"]:
                if self.reject_proposal(proposal["id"], str(account_id)):
                    # 提案者に通知
                    try:
                        self.notify_proposal_result(proposal, approved=False)
                    except Exception as e:
                        print(f"⚠️ 提案者への通知エラー: {e}")

                    return f"🙅 却下したウル！\n\n「{proposal['key']}: {proposal['value']}」は今回は見送りウル。\n{proposal['proposed_by_name']}さんにも伝えておくウル！"
                else:
                    return "😢 却下処理でエラーが起きたウル..."
            else:
                return None  # 承認でも却下でもない場合は一般会話として処理
        else:
            # 管理者以外が承認/却下しようとした場合
            return f"ありがとウル！🐺\n\nこの変更は菊地さんの最終承認が必要なウル！\n[To:{self.admin_account_id}] {sender_name}さんからも承認の声が出てるウル！確認お願いするウル！"

    def handle_proposal_by_id(
        self,
        proposal_id: int,
        decision: str,
        account_id: str,
        sender_name: str,
        room_id: str
    ) -> str:
        """
        ID指定で提案を承認/却下（v6.9.1追加）

        ローカルコマンド「承認 123」「却下 123」用

        Args:
            proposal_id: 提案ID
            decision: 判定（"approve" or "reject"）
            account_id: アカウントID
            sender_name: 発言者の名前
            room_id: ルームID

        Returns:
            応答メッセージ
        """
        # 管理部ルームかチェック
        if str(room_id) != str(self.admin_room_id):
            return "🤔 承認・却下は管理部ルームでお願いするウル！"

        # 管理者判定
        if not self.is_admin(account_id):
            return f"🙏 承認・却下は菊地さんだけができるウル！\n[To:{self.admin_account_id}] {sender_name}さんが提案ID={proposal_id}について操作しようとしたウル！"

        # 提案を取得
        proposal = self.get_proposal_by_id(proposal_id)

        if not proposal:
            return f"🤔 提案ID={proposal_id}は見つからなかったウル..."

        if proposal["status"] != "pending":
            return f"🤔 提案ID={proposal_id}は既に処理済みウル（{proposal['status']}）"

        if decision == "approve":
            if self.approve_proposal(proposal_id, str(account_id)):
                try:
                    self.notify_proposal_result(proposal, approved=True)
                except Exception as e:
                    print(f"⚠️ 提案者への通知エラー: {e}")
                return f"✅ 提案ID={proposal_id}を承認したウル！🐺\n\n「{proposal['key']}: {proposal['value']}」を覚えたウル！\n{proposal['proposed_by_name']}さんにも伝えておくウル！"
            else:
                return "😢 承認処理でエラーが起きたウル..."

        elif decision == "reject":
            if self.reject_proposal(proposal_id, str(account_id)):
                try:
                    self.notify_proposal_result(proposal, approved=False)
                except Exception as e:
                    print(f"⚠️ 提案者への通知エラー: {e}")
                return f"🙅 提案ID={proposal_id}を却下したウル！\n\n「{proposal['key']}: {proposal['value']}」は今回は見送りウル。\n{proposal['proposed_by_name']}さんにも伝えておくウル！"
            else:
                return "😢 却下処理でエラーが起きたウル..."

        return "🤔 承認か却下か分からなかったウル..."
