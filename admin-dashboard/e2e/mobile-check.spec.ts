/**
 * モバイル表示チェック — 全ページをiPhoneサイズで撮影
 */
import { test } from '@playwright/test';
import type { Route, Page } from '@playwright/test';

const MOCK_ME = {
  user_id: 'test-user-001', organization_id: 'test-org-001',
  name: 'テスト管理者', email: 'admin@test.com',
  role: 'admin', role_level: 5, department_id: null,
};

const MOCK_EMPTY: Record<string, unknown> = {
  status: 'success', data: [], members: [], goals: [], tasks: [], meetings: [],
  actions: [], insights: [], patterns: [], reports: [], diagnoses: [], metrics: [],
  logs: [], monthly: [], daily: [], by_model: [], by_tier: [], teachings: [],
  conflicts: [], alerts: [], trends: [], departments: [], top_keymen: [], forecasts: [],
  kpis: { total_conversations: 10, avg_response_time_ms: 300, error_rate: 0.01,
    total_cost_today: 100, monthly_budget_remaining: 1000, active_alerts_count: 0 },
  recent_alerts: [], recent_insights: [], generated_at: new Date().toISOString(),
  is_active: false, total_count: 0, total_goals: 0, active_goals: 0, completed_goals: 0,
  overdue_goals: 0, completion_rate: 0, by_department: [], total_actions: 0,
  positive_responses: 0, response_rate: 0, by_trigger_type: [], total_usages: 0,
  helpful_rate: 0, by_category: [],
};

async function setupMocks(page: Page) {
  await page.route('**/api/v1/admin/**', (route: Route) => {
    if (!route.request().isNavigationRequest())
      route.fulfill({ status: 200, json: MOCK_EMPTY });
    else
      route.continue();
  });
  await page.route('**/api/v1/admin/auth/me', (route: Route) =>
    route.fulfill({ json: MOCK_ME })
  );
}

const IPHONE = { width: 390, height: 844 };

const PAGES = [
  { name: 'morning', path: '/morning' },
  { name: 'dashboard', path: '/' },
  { name: 'members', path: '/members' },
  { name: 'goals', path: '/goals' },
  { name: 'costs', path: '/costs' },
  { name: 'teachings', path: '/teachings' },
];

test.describe('mobile screenshots', () => {
  for (const pg of PAGES) {
    test(`${pg.name}`, async ({ browser }) => {
      const context = await browser.newContext({
        viewport: IPHONE,
        userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
      });
      const page = await context.newPage();
      await setupMocks(page);
      await page.goto(`http://localhost:5173${pg.path}`);
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(500);
      await page.screenshot({
        path: `e2e/screenshots/mobile-after/${pg.name}.png`,
        fullPage: false,
      });
      console.log(`📸 ${pg.name}: saved`);
      await context.close();
    });
  }
});
