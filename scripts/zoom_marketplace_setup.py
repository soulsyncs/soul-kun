"""
Zoom Marketplace App 自動セットアップスクリプト
================================================
使い方:
  python3 scripts/zoom_marketplace_setup.py

手順:
  1. ブラウザが開く → Googleログインを手動で行う
  2. ログイン完了後、このターミナルで Enter を押す
  3. 以降は自動でアプリ作成 → 情報取得 → 管理画面登録まで完了

必要情報:
  - ADMIN_API_URL: 管理画面APIのURL
  - ADMIN_TOKEN:   管理画面のログイントークン（環境変数で指定）
"""

import asyncio
import os
import sys
import json
import httpx
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

ZOOM_MARKETPLACE_URL = "https://marketplace.zoom.us/"
WEBHOOK_URL = "https://chatwork-webhook-tzu7ftekzq-an.a.run.app/zoom-webhook"
ADMIN_API_BASE = "https://soulkun-api-tzu7ftekzq-an.a.run.app"

APP_NAME = "ソウルシンクス議事録Bot"
APP_DESCRIPTION = "Zoom録画完了時に自動で議事録を生成してChatWorkに送信するBot"


async def wait_for_user(message: str) -> str:
    print(f"\n{'='*60}")
    print(f"⏸️  {message}")
    print(f"{'='*60}")
    return input("👉 準備ができたら Enter を押してください: ")


async def setup_zoom_app():
    print("\n🚀 Zoom Marketplace セットアップを開始します")
    print(f"📌 Webhook URL: {WEBHOOK_URL}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )
        context = await browser.new_context(no_viewport=True)
        page = await context.new_page()

        # ① Zoom Marketplace を開く
        print("\n📂 Zoom Marketplace を開いています...")
        await page.goto(ZOOM_MARKETPLACE_URL)
        await page.wait_for_load_state("networkidle")

        # ② ログイン待ち
        await wait_for_user(
            "ブラウザが開きました。\n"
            "Zoom Marketplace に Google でログインしてください。\n"
            "ログインが完了したらここに戻って Enter を押してください。"
        )

        # ③ ログイン確認
        print("\n🔍 ログイン状態を確認中...")
        await page.wait_for_load_state("networkidle")

        # ④ 「Build」または「Develop」メニューへ
        print("\n📱 アプリ作成ページへ移動中...")
        try:
            await page.goto("https://marketplace.zoom.us/develop/create")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)
        except Exception:
            print("  直接アクセス失敗、メニューから移動します...")
            await page.goto(ZOOM_MARKETPLACE_URL)
            await page.wait_for_load_state("networkidle")

        # ⑤ 現在のURLを確認してログイン確認
        current_url = page.url
        print(f"  現在のURL: {current_url}")

        if "signin" in current_url or "login" in current_url:
            await wait_for_user(
                "まだログインが完了していないようです。\n"
                "ブラウザでログインしてから Enter を押してください。"
            )
            await page.goto("https://marketplace.zoom.us/develop/create")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)

        # ⑥ General App を選択
        print("\n🔧 General App を探しています...")
        try:
            # "General App" ボタンを探す
            general_app_btn = page.get_by_text("General App", exact=False).first
            if await general_app_btn.is_visible():
                print("  ✅ General App ボタンを発見")
                await general_app_btn.click()
                await asyncio.sleep(1)
            else:
                raise Exception("General App が見つかりません")
        except Exception as e:
            print(f"  ⚠️  自動選択失敗: {e}")
            await wait_for_user(
                "ブラウザで「General App」を選択してから Enter を押してください。\n"
                "（Develop → Build App → General App）"
            )

        # ⑦ アプリ名を入力して作成
        print(f"\n📝 アプリ名「{APP_NAME}」を入力中...")
        try:
            name_input = page.get_by_placeholder("App Name").or_(
                page.locator("input[name='app_name']")
            ).or_(
                page.locator("input[placeholder*='name' i]").first
            )
            await name_input.fill(APP_NAME)
            await asyncio.sleep(0.5)

            # 作成ボタン
            create_btn = page.get_by_role("button", name="Create").or_(
                page.get_by_text("Create", exact=True).first
            )
            await create_btn.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)
            print("  ✅ アプリを作成しました")
        except Exception as e:
            print(f"  ⚠️  自動入力失敗: {e}")
            await wait_for_user(
                f"ブラウザでアプリ名「{APP_NAME}」を入力して\n"
                "「Create」ボタンを押してから Enter を押してください。"
            )

        # ⑧ App Credentials タブから Account ID を取得
        print("\n🔑 Account ID を取得中...")
        account_id = None
        try:
            # App Credentials タブをクリック
            creds_tab = page.get_by_text("App Credentials", exact=False).first
            if await creds_tab.is_visible():
                await creds_tab.click()
                await asyncio.sleep(2)

            # Account ID を探す
            # "Account ID" というラベルの隣の値
            account_id_label = page.get_by_text("Account ID", exact=True).first
            if await account_id_label.is_visible():
                # 隣の要素や next sibling を探す
                parent = account_id_label.locator("..")
                value_el = parent.locator("input, code, span, p").last
                account_id = (await value_el.inner_text()).strip()
                if not account_id:
                    account_id = await value_el.get_attribute("value")
                print(f"  ✅ Account ID: {account_id[:8]}...")
        except Exception as e:
            print(f"  ⚠️  自動取得失敗: {e}")

        if not account_id:
            account_id = await wait_for_user(
                "ブラウザの「App Credentials」タブを開いて\n"
                "「Account ID」の値をコピーして、ここに貼り付けてください:"
            )

        account_id = account_id.strip()
        print(f"  Account ID: {account_id[:8]}...")

        # ⑨ Feature → Event Subscriptions から Secret Token を取得
        print("\n🔐 Webhook Secret Token を設定中...")

        # Feature タブへ
        try:
            feature_tab = page.get_by_text("Feature", exact=True).or_(
                page.get_by_text("Features", exact=True)
            ).first
            if await feature_tab.is_visible():
                await feature_tab.click()
                await asyncio.sleep(2)
        except Exception as e:
            print(f"  Feature タブへの移動失敗: {e}")

        # Event Subscriptions を有効化
        try:
            event_sub_toggle = page.get_by_text("Event Subscriptions").locator("..").locator("input[type=checkbox], button[role=switch]").first
            if await event_sub_toggle.is_visible():
                is_checked = await event_sub_toggle.is_checked()
                if not is_checked:
                    await event_sub_toggle.click()
                    await asyncio.sleep(1)
                print("  ✅ Event Subscriptions を有効化しました")
        except Exception as e:
            print(f"  ⚠️  トグル操作失敗（手動で有効化してください）: {e}")

        # Webhook URL を入力
        try:
            webhook_input = page.get_by_placeholder("https://").first
            await webhook_input.fill(WEBHOOK_URL)
            await asyncio.sleep(0.5)
            print(f"  ✅ Webhook URL を入力: {WEBHOOK_URL}")
        except Exception as e:
            print(f"  ⚠️  URL入力失敗: {e}")
            await wait_for_user(
                f"ブラウザの Event Subscriptions で\n"
                f"Webhook URL に以下を入力してください:\n"
                f"{WEBHOOK_URL}\n"
                "入力したら Enter を押してください。"
            )

        # Validate ボタン → Secret Token 取得
        secret_token = None
        try:
            validate_btn = page.get_by_role("button", name="Validate").or_(
                page.get_by_text("Validate", exact=True)
            ).first
            if await validate_btn.is_visible():
                await validate_btn.click()
                await asyncio.sleep(3)
                print("  ✅ Validate 完了")

            # Secret Token を探す
            secret_el = page.get_by_text("Secret Token").locator("..").locator("input, code").first
            if await secret_el.is_visible():
                secret_token = (await secret_el.get_attribute("value") or await secret_el.inner_text()).strip()
                if secret_token:
                    print(f"  ✅ Secret Token 取得: {secret_token[:4]}...")
        except Exception as e:
            print(f"  ⚠️  Secret Token 自動取得失敗: {e}")

        if not secret_token:
            secret_token = await wait_for_user(
                "ブラウザの Event Subscriptions から\n"
                "「Secret Token」の値をコピーして、ここに貼り付けてください:"
            )

        secret_token = secret_token.strip()

        # ⑩ アカウント名を聞く
        print("\n📋 登録情報の確認:")
        print(f"  Account ID     : {account_id}")
        print(f"  Secret Token   : {secret_token[:4]}****")
        print(f"  Webhook URL    : {WEBHOOK_URL}")

        account_name = input("\n👉 このZoomアカウントの管理用の名前を入力してください（例: 本社Zoom）: ").strip()
        if not account_name:
            account_name = "メインZoom"

        default_room_id = input("👉 デフォルトのChatWorkルームIDを入力してください（わからない場合は空でEnter）: ").strip() or None

        # ⑪ 管理画面APIへ登録
        print("\n🌐 管理画面に登録中...")

        admin_token = os.environ.get("ADMIN_TOKEN", "")
        if not admin_token:
            admin_token = input("👉 管理画面のログイントークンを入力してください（空の場合はスキップ）: ").strip()

        if admin_token:
            payload = {
                "account_name": account_name,
                "zoom_account_id": account_id,
                "webhook_secret_token": secret_token,
                "default_room_id": default_room_id,
                "is_active": True,
            }
            headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        f"{ADMIN_API_BASE}/api/v1/admin/zoom/accounts",
                        json=payload,
                        headers=headers,
                    )
                if resp.status_code in (200, 201):
                    print("  ✅ 管理画面への登録が完了しました！")
                else:
                    print(f"  ⚠️  登録に失敗しました（HTTP {resp.status_code}）: {resp.text}")
                    print("  以下の情報を管理画面から手動で入力してください。")
            except Exception as e:
                print(f"  ⚠️  API呼び出し失敗: {e}")
        else:
            print("  ⚠️  トークンなしのためAPIスキップ")

        # ⑫ 完了サマリー
        print("\n" + "="*60)
        print("✅ セットアップ完了！")
        print("="*60)
        print(f"  アカウント名   : {account_name}")
        print(f"  Account ID    : {account_id}")
        print(f"  Secret Token  : {secret_token[:4]}****")
        print(f"  Webhook URL   : {WEBHOOK_URL}")
        print("\n管理画面に未登録の場合は以下の情報を使って手動登録してください。")
        print(f"  POST {ADMIN_API_BASE}/api/v1/admin/zoom/accounts")
        print(json.dumps({
            "account_name": account_name,
            "zoom_account_id": account_id,
            "webhook_secret_token": secret_token,
            "default_room_id": default_room_id,
            "is_active": True,
        }, ensure_ascii=False, indent=2))

        input("\n👉 完了を確認したら Enter を押してブラウザを閉じます: ")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(setup_zoom_app())
