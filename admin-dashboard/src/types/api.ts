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

export interface BudgetUpdateRequest {
  year_month: string;
  budget_jpy: number;
}

export interface BudgetUpdateResponse {
  status: string;
  year_month: string;
  budget_jpy: number;
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

// =============================================================================
// Departments / Org Chart
// =============================================================================

export interface DepartmentTreeNode {
  id: string;
  name: string;
  parent_department_id: string | null;
  level: number;
  display_order: number;
  description: string | null;
  is_active: boolean;
  member_count: number;
  children: DepartmentTreeNode[];
}

export interface DepartmentsTreeResponse {
  status: string;
  departments: DepartmentTreeNode[];
  total_count: number;
}

export interface DepartmentMember {
  user_id: string;
  name: string | null;
  role: string | null;
  role_level: number | null;
  is_primary: boolean;
}

export interface DepartmentResponse {
  id: string;
  name: string;
  parent_department_id: string | null;
  level: number;
  display_order: number;
  description: string | null;
  is_active: boolean;
  member_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface DepartmentDetailResponse {
  status: string;
  department: DepartmentResponse;
  members: DepartmentMember[];
}

export interface DepartmentMutationResponse {
  status: string;
  department_id: string;
  message: string;
}

export interface MemberDepartmentInfo {
  department_id: string;
  department_name: string;
  role: string | null;
  role_level: number | null;
  is_primary: boolean;
}

export interface MemberDetailResponse {
  status: string;
  user_id: string;
  name: string | null;
  email: string | null;
  role: string | null;
  role_level: number | null;
  departments: MemberDepartmentInfo[];
  chatwork_account_id: string | null;
  is_active: boolean;
  avatar_url: string | null;
  employment_type: string | null;
  evaluation: string | null;
  goal_achievement: number | null;
  skills: string[];
  notes: string | null;
  phone: string | null;
  birthday: string | null;
  hire_date: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CreateDepartmentRequest {
  name: string;
  parent_department_id?: string | null;
  description?: string | null;
  display_order?: number;
}

export interface UpdateDepartmentRequest {
  name?: string;
  parent_department_id?: string | null;
  description?: string | null;
  display_order?: number;
}

export interface CreateMemberRequest {
  name: string;
  email?: string;
  chatwork_account_id?: string;
  role?: string;
  department_id?: string;
  role_id?: string;
}

export interface UpdateMemberRequest {
  name?: string;
  email?: string;
  chatwork_account_id?: string;
  employment_type?: string;
  avatar_url?: string;
  evaluation?: string;
  goal_achievement?: number | null;
  skills?: string[] | null;
  notes?: string | null;
  phone?: string | null;
  birthday?: string | null;
}

export interface MemberDepartmentAssignment {
  department_id: string;
  role_id: string;
  is_primary: boolean;
}

export interface UpdateMemberDepartmentsRequest {
  departments: MemberDepartmentAssignment[];
}

// =============================================================================
// Roles (for department assignment)
// =============================================================================

export interface RoleResponse {
  id: string;
  name: string;
  level: number;
  description: string | null;
}

// =============================================================================
// Phase 2: Goals
// =============================================================================

export interface GoalSummary {
  id: string;
  user_id: string;
  user_name: string | null;
  department_name: string | null;
  title: string;
  goal_type: string;
  goal_level: string;
  status: string;
  period_type: string;
  period_start: string | null;
  period_end: string | null;
  deadline: string | null;
  target_value: number | null;
  current_value: number | null;
  unit: string | null;
  progress_pct: number | null;
}

export interface GoalsListResponse {
  status: string;
  goals: GoalSummary[];
  total_count: number;
}

export interface GoalProgressEntry {
  id: string;
  progress_date: string;
  value: number | null;
  cumulative_value: number | null;
  daily_note: string | null;
}

export interface GoalDetailResponse {
  status: string;
  goal: GoalSummary;
  progress: GoalProgressEntry[];
}

export interface GoalStatsResponse {
  status: string;
  total_goals: number;
  active_goals: number;
  completed_goals: number;
  overdue_goals: number;
  completion_rate: number;
  by_department: Array<{
    department: string;
    total: number;
    completed: number;
    rate: number;
  }>;
}

// =============================================================================
// Phase 2: Wellness / Emotion
// =============================================================================

export interface EmotionAlertSummary {
  id: string;
  user_id: string;
  user_name: string | null;
  department_name: string | null;
  alert_type: string;
  risk_level: string;
  baseline_score: number | null;
  current_score: number | null;
  score_change: number | null;
  consecutive_negative_days: number | null;
  status: string;
  first_detected_at: string | null;
  last_detected_at: string | null;
}

export interface EmotionAlertsResponse {
  status: string;
  alerts: EmotionAlertSummary[];
  total_count: number;
}

export interface EmotionTrendEntry {
  date: string;
  avg_score: number;
  message_count: number;
  negative_count: number;
  positive_count: number;
}

export interface EmotionTrendsResponse {
  status: string;
  trends: EmotionTrendEntry[];
  period_start: string | null;
  period_end: string | null;
}

// =============================================================================
// Phase 2: Tasks
// =============================================================================

export interface TaskOverviewStats {
  status: string;
  chatwork_tasks: {
    total: number;
    open: number;
    done: number;
    overdue: number;
  };
  autonomous_tasks: {
    total: number;
    pending: number;
    running: number;
    completed: number;
    failed: number;
  };
  detected_tasks: {
    total: number;
    processed: number;
    unprocessed: number;
  };
}

export interface TaskItem {
  id: string;
  source: string;
  title: string;
  status: string;
  assignee_name: string | null;
  deadline: string | null;
  created_at: string | null;
}

export interface TaskListResponse {
  status: string;
  tasks: TaskItem[];
  total_count: number;
}

// =============================================================================
// Phase 3: Insights
// =============================================================================

export interface InsightDetail {
  id: string;
  insight_type: string;
  source_type: string;
  importance: string;
  title: string;
  description: string;
  recommended_action: string | null;
  status: string;
  department_name: string | null;
  created_at: string | null;
}

export interface InsightsListResponse {
  status: string;
  insights: InsightDetail[];
  total_count: number;
}

export interface QuestionPatternSummary {
  id: string;
  question_category: string;
  normalized_question: string;
  occurrence_count: number;
  last_asked_at: string | null;
  status: string;
}

export interface QuestionPatternsResponse {
  status: string;
  patterns: QuestionPatternSummary[];
  total_count: number;
}

export interface WeeklyReportSummary {
  id: string;
  week_start: string;
  week_end: string;
  status: string;
  sent_at: string | null;
  sent_via: string | null;
}

export interface WeeklyReportsResponse {
  status: string;
  reports: WeeklyReportSummary[];
  total_count: number;
}

// =============================================================================
// Phase 3: Meetings
// =============================================================================

export interface MeetingSummary {
  id: string;
  title: string | null;
  meeting_type: string;
  meeting_date: string | null;
  duration_seconds: number | null;
  status: string;
  source: string;
  has_transcript: boolean;
  has_recording: boolean;
}

export interface MeetingsListResponse {
  status: string;
  meetings: MeetingSummary[];
  total_count: number;
}

export interface MeetingDetailResponse {
  status: string;
  meeting: {
    id: string;
    title: string | null;
    meeting_type: string;
    meeting_date: string | null;
    duration_seconds: number | null;
    status: string;
    source: string;
  };
  transcript: string | null;
}

// =============================================================================
// Phase 3: Proactive
// =============================================================================

export interface ProactiveActionSummary {
  id: string;
  user_id: string;
  trigger_type: string;
  priority: string;
  message_type: string;
  user_response_positive: boolean | null;
  created_at: string | null;
}

export interface ProactiveActionsResponse {
  status: string;
  actions: ProactiveActionSummary[];
  total_count: number;
}

export interface ProactiveStatsResponse {
  status: string;
  total_actions: number;
  positive_responses: number;
  response_rate: number;
  by_trigger_type: Array<{
    trigger_type: string;
    total: number;
    positive: number;
  }>;
}

// =============================================================================
// Phase 4: Teachings
// =============================================================================

export const TEACHING_CATEGORIES = [
  { value: 'mvv_mission', label: 'MVV（ミッション）' },
  { value: 'mvv_vision', label: 'MVV（ビジョン）' },
  { value: 'mvv_values', label: 'MVV（バリューズ）' },
  { value: 'choice_theory', label: '選択理論' },
  { value: 'sdt', label: '自己決定理論' },
  { value: 'servant', label: 'サーバントリーダーシップ' },
  { value: 'psych_safety', label: '心理的安全性' },
  { value: 'biz_sales', label: '業務（営業）' },
  { value: 'biz_hr', label: '業務（人事）' },
  { value: 'biz_accounting', label: '業務（経理）' },
  { value: 'biz_general', label: '業務（一般）' },
  { value: 'culture', label: '組織文化' },
  { value: 'communication', label: 'コミュニケーション' },
  { value: 'staff_guidance', label: 'スタッフ指導' },
  { value: 'other', label: 'その他' },
] as const;

export type TeachingCategoryValue = typeof TEACHING_CATEGORIES[number]['value'];

export interface CreateTeachingRequest {
  statement: string;
  category: TeachingCategoryValue;
  subcategory?: string;
  priority?: number;
  reasoning?: string;
}

export interface TeachingMutationResponse {
  status: string;
  teaching_id: string;
  message: string;
}

export interface TeachingSummary {
  id: string;
  category: string;
  subcategory: string | null;
  statement: string;
  validation_status: string;
  priority: number | null;
  is_active: boolean | null;
  usage_count: number | null;
  helpful_count: number | null;
  last_used_at: string | null;
}

export interface TeachingsListResponse {
  status: string;
  teachings: TeachingSummary[];
  total_count: number;
}

export interface TeachingConflictSummary {
  id: string;
  teaching_id: string;
  conflict_type: string;
  severity: string;
  description: string;
  conflicting_teaching_id: string | null;
  created_at: string | null;
}

export interface TeachingConflictsResponse {
  status: string;
  conflicts: TeachingConflictSummary[];
  total_count: number;
}

export interface TeachingUsageStatsResponse {
  status: string;
  total_usages: number;
  helpful_rate: number;
  by_category: Array<{
    category: string;
    usage_count: number;
    helpful_count: number;
  }>;
}

// =============================================================================
// Phase 4: System Health
// =============================================================================

export interface SystemHealthSummary {
  status: string;
  latest_date: string | null;
  total_conversations: number;
  unique_users: number;
  avg_response_time_ms: number | null;
  p95_response_time_ms: number | null;
  success_rate: number;
  error_count: number;
  avg_confidence: number | null;
}

export interface DailyMetricEntry {
  metric_date: string;
  total_conversations: number;
  unique_users: number;
  avg_response_time_ms: number | null;
  success_count: number;
  error_count: number;
  avg_confidence: number | null;
}

export interface SystemMetricsResponse {
  status: string;
  metrics: DailyMetricEntry[];
}

export interface SelfDiagnosisSummary {
  id: string;
  diagnosis_type: string;
  period_start: string | null;
  period_end: string | null;
  overall_score: number;
  total_interactions: number;
  successful_interactions: number;
  identified_weaknesses: string[] | null;
}

export interface SelfDiagnosesResponse {
  status: string;
  diagnoses: SelfDiagnosisSummary[];
  total_count: number;
}

// =============================================================================
// Phase 2 新機能: AI ROI
// =============================================================================

export interface AiRoiTierBreakdown {
  tier: string;
  requests: number;
  cost_jpy: number;
  time_saved_hours: number;
  labor_saved_jpy: number;
}

export interface AiRoiResponse {
  status: string;
  days: number;
  total_cost_jpy: number;
  total_requests: number;
  time_saved_hours: number;
  labor_saved_jpy: number;
  roi_multiplier: number;
  by_tier: AiRoiTierBreakdown[];
}

// =============================================================================
// Phase 2 新機能: Teaching Penetration
// =============================================================================

export interface TeachingPenetrationItem {
  id: string;
  statement: string;
  category: string;
  usage_count: number;
  penetration_pct: number;
}

export interface TeachingPenetrationCategory {
  category: string;
  total_teachings: number;
  used_teachings: number;
  total_usages: number;
  penetration_pct: number;
}

export interface TeachingPenetrationResponse {
  status: string;
  total_teachings: number;
  used_teachings: number;
  total_usages: number;
  overall_penetration_pct: number;
  by_category: TeachingPenetrationCategory[];
  top_teachings: TeachingPenetrationItem[];
  unused_teachings: TeachingPenetrationItem[];
}

// =============================================================================
// Phase 3 新機能: Goal Forecast（目標未来予測）
// =============================================================================

export interface GoalForecastItem {
  id: string;
  title: string;
  user_name: string | null;
  department_name: string | null;
  forecast_status: string; // ahead / on_track / at_risk / stalled / no_data
  progress_pct: number | null;
  deadline: string | null;
  projected_completion_date: string | null;
  days_to_deadline: number | null;
  days_ahead_or_behind: number | null;
  current_value: number | null;
  target_value: number | null;
  unit: string | null;
  slope_per_day: number | null;
}

export interface GoalForecastResponse {
  status: string;
  total_active: number;
  ahead_count: number;
  on_track_count: number;
  at_risk_count: number;
  stalled_count: number;
  forecasts: GoalForecastItem[];
}

// =============================================================================
// Phase 3 新機能: Key Person Score（隠れたキーマン発見）
// =============================================================================

export interface KeyPersonScore {
  user_id: string;
  name: string | null;
  department_name: string | null;
  total_requests: number;
  active_days: number;
  tiers_used: number;
  score: number;
  rank: number;
  recent_trend: string; // rising / stable / declining
}

export interface KeymenResponse {
  status: string;
  period_days: number;
  top_keymen: KeyPersonScore[];
}

// =============================================================================
// Emergency Stop
// =============================================================================

export interface EmergencyStopStatusResponse {
  status: string;
  is_active: boolean;
  activated_by: string | null;
  deactivated_by: string | null;
  reason: string | null;
  activated_at: string | null;
  deactivated_at: string | null;
}

export interface EmergencyStopActionResponse {
  status: string;
  message: string;
  is_active: boolean;
}
