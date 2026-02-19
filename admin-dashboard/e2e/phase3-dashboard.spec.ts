/**
 * Phase 3 管理ダッシュボード 動作確認テスト
 * - ⑦ 目標の未来予測タブ
 * - ④ 隠れたキーマン発見タブ
 *
 * API は全てモック（route intercept）で実行。
 * ※ Playwright のルートマッチは LIFO（後登録が優先）のため、
 *    catch-all を先に、具体的なルートを後に登録する。
 */

import { test, expect } from '@playwright/test';
import type { Route } from '@playwright/test';

// =============== モックデータ ===============

const MOCK_ME = {
  user_id: 'test-user-001',
  organization_id: 'test-org-001',
  name: 'テスト管理者',
  email: 'admin@test.com',
  role: 'admin',
  role_level: 5,
  department_id: null,
};

const MOCK_GOAL_STATS = {
  status: 'success',
  total_goals: 12,
  active_goals: 8,
  completed_goals: 3,
  overdue_goals: 1,
  completion_rate: 25.0,
  by_department: [],
};

const MOCK_GOALS_LIST = {
  status: 'success',
  goals: [
    {
      id: 'g001',
      user_id: 'u001',
      user_name: '山田 太郎',
      department_name: '営業部',
      title: '今期売上目標 1000万円',
      goal_type: 'sales',
      goal_level: 'individual',
      status: 'active',
      period_type: 'quarterly',
      period_start: '2026-01-01',
      period_end: '2026-03-31',
      deadline: '2026-03-31',
      target_value: 10000000,
      current_value: 4500000,
      unit: '円',
      progress_pct: 45.0,
    },
  ],
  total_count: 1,
};

const MOCK_FORECAST = {
  status: 'success',
  total_active: 8,
  ahead_count: 2,
  on_track_count: 3,
  at_risk_count: 2,
  stalled_count: 1,
  forecasts: [
    {
      id: 'g001',
      title: '今期売上目標 1000万円',
      user_name: '山田 太郎',
      department_name: '営業部',
      forecast_status: 'on_track',
      progress_pct: 45.0,
      deadline: '2026-03-31',
      projected_completion_date: '2026-03-28',
      days_to_deadline: 39,
      days_ahead_or_behind: -3,
      current_value: 4500000,
      target_value: 10000000,
      unit: '円',
      slope_per_day: 75000,
    },
    {
      id: 'g002',
      title: '新規顧客開拓 10社',
      user_name: '鈴木 花子',
      department_name: '営業部',
      forecast_status: 'at_risk',
      progress_pct: 20.0,
      deadline: '2026-03-31',
      projected_completion_date: '2026-05-15',
      days_to_deadline: 39,
      days_ahead_or_behind: 45,
      current_value: 2,
      target_value: 10,
      unit: '社',
      slope_per_day: 0.05,
    },
  ],
};

const MOCK_MEMBERS_LIST = {
  status: 'success',
  members: [
    {
      user_id: 'u001',
      name: '山田 太郎',
      email: 'yamada@test.com',
      role: '営業担当',
      role_level: 2,
      department: '営業部',
      department_id: 'd001',
      created_at: '2025-01-15T00:00:00Z',
    },
  ],
  total_count: 1,
  offset: 0,
  limit: 20,
};

const MOCK_KEYMEN = {
  status: 'success',
  period_days: 90,
  top_keymen: [
    {
      user_id: 'u001',
      name: '山田 太郎',
      department_name: '営業部',
      total_requests: 342,
      active_days: 58,
      tiers_used: 4,
      score: 87.5,
      rank: 1,
      recent_trend: 'rising',
    },
    {
      user_id: 'u002',
      name: '鈴木 花子',
      department_name: 'マーケティング部',
      total_requests: 215,
      active_days: 42,
      tiers_used: 3,
      score: 62.3,
      rank: 2,
      recent_trend: 'stable',
    },
  ],
};

const MOCK_DASHBOARD = {
  status: 'success',
  period: 'today',
  kpis: {
    total_conversations: 42,
    avg_response_time_ms: 380,
    error_rate: 0.02,
    total_cost_today: 150,
    monthly_budget_remaining: 5000,
    active_alerts_count: 0,
  },
  recent_alerts: [],
  recent_insights: [],
  generated_at: new Date().toISOString(),
};

// =============== API モック設定 ===============
// 重要: Playwright は LIFO（後登録が優先）。
// catch-all を先に、具体的なルートを後に登録する。

async function setupApiMocks(page: import('@playwright/test').Page) {
  // 1. catch-all（一番先に登録 = 最低優先度）
  await page.route('**/api/v1/admin/**', (route: Route) => {
    const url = route.request().url();
    // ナビゲーション以外はデフォルトレスポンス
    if (!route.request().isNavigationRequest()) {
      route.fulfill({ status: 200, json: { status: 'success', data: [] } });
    } else {
      route.continue();
    }
    void url; // suppress unused warning
  });

  // 2. Dashboard
  await page.route('**/api/v1/admin/dashboard/**', (route: Route) =>
    route.fulfill({ json: MOCK_DASHBOARD })
  );

  // 3. Goals
  await page.route('**/api/v1/admin/goals', (route: Route) =>
    route.fulfill({ json: MOCK_GOALS_LIST })
  );
  await page.route('**/api/v1/admin/goals?*', (route: Route) =>
    route.fulfill({ json: MOCK_GOALS_LIST })
  );
  await page.route('**/api/v1/admin/goals/stats', (route: Route) =>
    route.fulfill({ json: MOCK_GOAL_STATS })
  );
  await page.route('**/api/v1/admin/goals/forecast', (route: Route) =>
    route.fulfill({ json: MOCK_FORECAST })
  );

  // 4. Members
  await page.route('**/api/v1/admin/members', (route: Route) =>
    route.fulfill({ json: MOCK_MEMBERS_LIST })
  );
  await page.route('**/api/v1/admin/members?*', (route: Route) =>
    route.fulfill({ json: MOCK_MEMBERS_LIST })
  );
  await page.route('**/api/v1/admin/members/keymen', (route: Route) =>
    route.fulfill({ json: MOCK_KEYMEN })
  );
  await page.route('**/api/v1/admin/members/keymen?*', (route: Route) =>
    route.fulfill({ json: MOCK_KEYMEN })
  );

  // 5. 認証（最後に登録 = 最高優先度）
  await page.route('**/api/v1/admin/auth/me', (route: Route) =>
    route.fulfill({ json: MOCK_ME })
  );
  await page.route('**/api/v1/admin/auth/token-login', (route: Route) =>
    route.fulfill({ json: { access_token: 'mock-token', token_type: 'bearer', expires_in: 3600 } })
  );
}

// =============== テスト本体 ===============

test.describe('Phase 3 ダッシュボード機能確認', () => {

  test('① 目標管理ページが開く', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto('/goals');
    await page.waitForLoadState('networkidle');

    // h1 は複数あるためページ内の h1（メインコンテンツ）を特定
    const heading = page.getByRole('heading', { name: '目標管理' });
    await expect(heading).toBeVisible({ timeout: 10000 });
    console.log('✅ 目標管理ページ: 表示OK');

    await page.screenshot({ path: 'e2e/screenshots/goals-page.png', fullPage: true });
  });

  test('② 「目標未来予測」タブが表示されてクリックできる', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto('/goals');
    await page.waitForLoadState('networkidle');

    // タブが存在するか
    const forecastTab = page.getByRole('button', { name: /目標未来予測/ });
    await expect(forecastTab).toBeVisible({ timeout: 10000 });
    console.log('✅ 「目標未来予測」タブ: 表示OK');

    // タブをクリック
    await forecastTab.click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(300);

    // サマリーカード（4種類）が表示されるか
    await expect(page.getByText('順調（前倒し）').first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('予定通り').first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('遅れ気味').first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('停滞中').first()).toBeVisible({ timeout: 5000 });
    console.log('✅ 目標予測サマリーカード（4種類）: 表示OK');

    // 目標リストのアイテムが表示されるか
    await expect(page.getByText('今期売上目標 1000万円')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('新規顧客開拓 10社')).toBeVisible({ timeout: 5000 });
    console.log('✅ 目標別予測リスト: 表示OK');

    // 符号ロジック確認（days_ahead_or_behind: -3 → 前倒し）
    await expect(page.getByText('3日 前倒し')).toBeVisible({ timeout: 5000 });
    // 正の値（45日遅れ）
    await expect(page.getByText('45日 遅れ')).toBeVisible({ timeout: 5000 });
    console.log('✅ 前倒し・遅れの表示ロジック: 正常');

    await page.screenshot({ path: 'e2e/screenshots/goal-forecast.png', fullPage: true });
    console.log('📸 スクリーンショット: e2e/screenshots/goal-forecast.png');
  });

  test('③ メンバーページが開く', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto('/members');
    await page.waitForLoadState('networkidle');

    const heading = page.getByRole('heading', { name: 'メンバー' });
    await expect(heading).toBeVisible({ timeout: 10000 });
    console.log('✅ メンバーページ: 表示OK');
  });

  test('④ 「隠れたキーマン発見」タブが表示されてクリックできる', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto('/members');
    await page.waitForLoadState('networkidle');

    // タブが存在するか
    const keymenTab = page.getByRole('button', { name: /隠れたキーマン発見/ });
    await expect(keymenTab).toBeVisible({ timeout: 10000 });
    console.log('✅ 「隠れたキーマン発見」タブ: 表示OK');

    // タブをクリック
    await keymenTab.click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(300);

    // タイトル確認
    await expect(page.getByText('AIキーマン スコアランキング')).toBeVisible({ timeout: 5000 });
    console.log('✅ キーマンランキングタイトル: 表示OK');

    // 1位 山田 太郎（スコア87.5）
    await expect(page.getByText('山田 太郎')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('87.5')).toBeVisible({ timeout: 5000 });
    console.log('✅ キーマン1位（山田 太郎, 87.5pt）: 表示OK');

    // 2位 鈴木 花子
    await expect(page.getByText('鈴木 花子')).toBeVisible({ timeout: 5000 });
    console.log('✅ キーマン2位（鈴木 花子）: 表示OK');

    // メダル表示
    await expect(page.getByText('🥇')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('🥈')).toBeVisible({ timeout: 5000 });
    console.log('✅ 順位メダル（🥇🥈）: 表示OK');

    await page.screenshot({ path: 'e2e/screenshots/keymen-ranking.png', fullPage: true });
    console.log('📸 スクリーンショット: e2e/screenshots/keymen-ranking.png');
  });

  test('⑤ 目標ページでタブを往復できる', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto('/goals');
    await page.waitForLoadState('networkidle');

    // 目標未来予測タブへ
    const forecastTab = page.getByRole('button', { name: /目標未来予測/ });
    await expect(forecastTab).toBeVisible({ timeout: 10000 });
    await forecastTab.click();
    await page.waitForTimeout(300);
    await expect(page.getByText('目標別 未来予測')).toBeVisible({ timeout: 5000 });
    console.log('✅ 目標未来予測タブ: 表示OK');

    // 目標一覧タブへ戻る
    await page.getByRole('button', { name: /目標一覧/ }).click();
    await page.waitForTimeout(300);
    await expect(page.getByText('今期売上目標 1000万円')).toBeVisible({ timeout: 5000 });
    console.log('✅ 目標一覧タブへ戻る: OK');
    console.log('✅ タブ切り替え（往復）: 正常動作');
  });

});
