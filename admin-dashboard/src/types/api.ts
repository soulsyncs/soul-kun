/**
 * TypeScript types for Admin Dashboard API responses
 * Aligned with backend Pydantic schemas (api/app/schemas/admin.py)
 */

// =============================================================================
// Auth
// =============================================================================

export interface User {
  user_id: string;
  organization_id: string;
  name: string | null;
  email: string | null;
  role: string | null;
  role_level: number;
  department_id: string | null;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface AuthMeResponse {
  user_id: string;
  organization_id: string;
  name: string | null;
  email: string | null;
  role: string | null;
  role_level: number;
  department_id: string | null;
}

// =============================================================================
// Dashboard
// =============================================================================

export interface DashboardKPIs {
  total_conversations: number;
  avg_response_time_ms: number;
  error_rate: number;
  total_cost_today: number;
  monthly_budget_remaining: number;
  active_alerts_count: number;
}

export interface AlertSummary {
  id: string;
  alert_type: string;
  severity: string;
  message: string;
  created_at: string;
  is_resolved: boolean;
}

export interface InsightSummary {
  id: string;
  insight_type: string;
  title: string;
  summary: string;
  created_at: string;
}

export interface DashboardSummaryResponse {
  status: string;
  period: string;
  kpis: DashboardKPIs;
  recent_alerts: AlertSummary[];
  recent_insights: InsightSummary[];
  generated_at: string;
}

// =============================================================================
// Brain Analytics
// =============================================================================

export interface BrainDailyMetric {
  date: string;
  conversations: number;
  avg_latency_ms: number;
  error_rate: number;
  cost: number;
}

export interface BrainMetricsResponse {
  status: string;
  days: number;
  metrics: BrainDailyMetric[];
}

export interface BrainLogEntry {
  id: string;
  created_at: string;
  selected_action: string;
  decision_confidence: number | null;
  total_time_ms: number | null;
}

export interface BrainLogsResponse {
  status: string;
  logs: BrainLogEntry[];
  total_count: number;
  offset: number;
  limit: number;
}

// =============================================================================
// Cost Tracking
// =============================================================================

export interface CostMonthlyEntry {
  year_month: string;
  total_cost: number;
  requests: number;
  budget: number | null;
  status: string;
}

export interface CostMonthlyResponse {
  status: string;
  months: CostMonthlyEntry[];
}

export interface CostDailyEntry {
  date: string;
  cost: number;
  requests: number;
}

export interface CostDailyResponse {
  status: string;
  days: number;
  daily: CostDailyEntry[];
}

export interface CostModelBreakdown {
  model: string;
  cost: number;
  requests: number;
  pct: number;
}

export interface CostTierBreakdown {
  tier: string;
  cost: number;
  requests: number;
  pct: number;
}

export interface CostBreakdownResponse {
  status: string;
  days: number;
  by_model: CostModelBreakdown[];
  by_tier: CostTierBreakdown[];
}

// =============================================================================
// Members
// =============================================================================

export interface MemberResponse {
  user_id: string;
  name: string | null;
  email: string | null;
  role: string | null;
  role_level: number | null;
  department: string | null;
  department_id: string | null;
  created_at: string | null;
}

export interface MembersListResponse {
  status: string;
  members: MemberResponse[];
  total_count: number;
  offset: number;
  limit: number;
}
