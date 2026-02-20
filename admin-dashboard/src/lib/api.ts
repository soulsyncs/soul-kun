/**
 * API Client for Soul-kun Admin Dashboard
 *
 * All endpoints are prefixed with /admin (matching FastAPI router prefix).
 * Uses httpOnly cookies for authentication (credentials: 'include').
 */

import type {
  AuthTokenResponse,
  AuthMeResponse,
  DashboardSummaryResponse,
  BrainMetricsResponse,
  BrainLogsResponse,
  CostMonthlyResponse,
  CostDailyResponse,
  CostBreakdownResponse,
  BudgetUpdateRequest,
  BudgetUpdateResponse,
  MembersListResponse,
  MemberResponse,
  DepartmentsTreeResponse,
  DepartmentDetailResponse,
  DepartmentMutationResponse,
  MemberDetailResponse,
  CreateDepartmentRequest,
  UpdateDepartmentRequest,
  UpdateMemberRequest,
  UpdateMemberDepartmentsRequest,
  EmergencyStopStatusResponse,
  EmergencyStopActionResponse,
} from '@/types/api';

const API_BASE_URL =
  (import.meta.env.VITE_API_URL || 'http://localhost:8080/api/v1').trim();

export class ApiError extends Error {
  public status: number;
  public data?: unknown;

  constructor(message: string, status: number, data?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

interface RequestOptions extends RequestInit {
  params?: Record<string, string | number | boolean | undefined>;
}

// In-memory Bearer token (used for cross-origin token-login flow)
// Also persisted to sessionStorage so page reloads don't require re-login
const _TOKEN_KEY = 'soulkun_admin_token';
let _bearerToken: string | null = null;

// Restore token from sessionStorage on module load (survives page refresh)
try {
  const saved = sessionStorage.getItem(_TOKEN_KEY);
  if (saved) { _bearerToken = saved; }
} catch { /* ignore */ }

export function setBearerToken(token: string) {
  _bearerToken = token;
  try { sessionStorage.setItem(_TOKEN_KEY, token); } catch { /* ignore */ }
}

export function clearBearerToken() {
  _bearerToken = null;
  try { sessionStorage.removeItem(_TOKEN_KEY); } catch { /* ignore */ }
}

async function fetchWithAuth<T>(
  endpoint: string,
  options: RequestOptions = {}
): Promise<T> {
  const { params, ...fetchOptions } = options;

  // Build URL with query parameters
  let url = `${API_BASE_URL}${endpoint}`;
  if (params) {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined) {
        searchParams.append(key, String(value));
      }
    });
    const queryString = searchParams.toString();
    if (queryString) {
      url += `?${queryString}`;
    }
  }

  const authHeaders: Record<string, string> = {};
  if (_bearerToken) {
    authHeaders['Authorization'] = `Bearer ${_bearerToken}`;
  }

  const config: RequestInit = {
    ...fetchOptions,
    credentials: 'include', // httpOnly cookie auth (fallback)
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
      ...authHeaders,
      ...fetchOptions.headers,
    },
  };

  const response = await fetch(url, config);

  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
    let errorData: unknown;

    try {
      errorData = await response.json();
      if (errorData && typeof errorData === 'object' && 'detail' in errorData) {
        const detail = (errorData as Record<string, unknown>).detail;
        if (typeof detail === 'string') {
          errorMessage = detail;
        } else if (
          detail &&
          typeof detail === 'object' &&
          'error_message' in (detail as Record<string, unknown>)
        ) {
          errorMessage = String(
            (detail as Record<string, string>).error_message
          );
        }
      }
    } catch {
      // Response body is not JSON
    }

    throw new ApiError(errorMessage, response.status, errorData);
  }

  return response.json() as Promise<T>;
}

export const api = {
  // Auth endpoints
  auth: {
    loginWithGoogle: (idToken: string) =>
      fetchWithAuth<AuthTokenResponse>('/admin/auth/google', {
        method: 'POST',
        body: JSON.stringify({ id_token: idToken }),
      }),

    loginWithToken: (token: string) =>
      fetchWithAuth<AuthTokenResponse>('/admin/auth/token-login', {
        method: 'POST',
        body: JSON.stringify({ token }),
      }),

    me: () => fetchWithAuth<AuthMeResponse>('/admin/auth/me'),

    logout: () =>
      fetchWithAuth<{ status: string }>('/admin/auth/logout', {
        method: 'POST',
      }),
  },

  // Dashboard endpoints
  dashboard: {
    getSummary: (period: 'today' | '7d' | '30d' = 'today') =>
      fetchWithAuth<DashboardSummaryResponse>('/admin/dashboard/summary', {
        params: { period },
      }),
  },

  // Brain analytics endpoints
  brain: {
    getMetrics: (days = 7) =>
      fetchWithAuth<BrainMetricsResponse>('/admin/brain/metrics', {
        params: { days },
      }),

    getLogs: (limit = 50, offset = 0) =>
      fetchWithAuth<BrainLogsResponse>('/admin/brain/logs', {
        params: { limit, offset },
      }),
  },

  // Cost tracking endpoints
  costs: {
    getMonthly: () =>
      fetchWithAuth<CostMonthlyResponse>('/admin/costs/monthly'),

    getDaily: (days = 30) =>
      fetchWithAuth<CostDailyResponse>('/admin/costs/daily', {
        params: { days },
      }),

    getBreakdown: (days = 30) =>
      fetchWithAuth<CostBreakdownResponse>('/admin/costs/breakdown', {
        params: { days },
      }),

    getAiRoi: (days = 30) =>
      fetchWithAuth<import('@/types/api').AiRoiResponse>('/admin/costs/ai-roi', {
        params: { days },
      }),

    updateBudget: (body: BudgetUpdateRequest) =>
      fetchWithAuth<BudgetUpdateResponse>('/admin/costs/budget', {
        method: 'PUT',
        body: JSON.stringify(body),
      }),
  },

  // Members endpoints
  members: {
    getList: (params?: {
      search?: string;
      dept_id?: string;
      limit?: number;
      offset?: number;
    }) => fetchWithAuth<MembersListResponse>('/admin/members', { params }),

    getDetail: (userId: string) =>
      fetchWithAuth<MemberResponse>(`/admin/members/${userId}`),

    getFullDetail: (userId: string) =>
      fetchWithAuth<MemberDetailResponse>(`/admin/members/${userId}/detail`),

    getKeymen: (periodDays = 90) =>
      fetchWithAuth<import('@/types/api').KeymenResponse>('/admin/members/keymen', {
        params: { period_days: periodDays },
      }),

    update: (userId: string, data: UpdateMemberRequest) =>
      fetchWithAuth<DepartmentMutationResponse>(`/admin/members/${userId}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      }),

    updateDepartments: (userId: string, data: UpdateMemberDepartmentsRequest) =>
      fetchWithAuth<DepartmentMutationResponse>(
        `/admin/members/${userId}/departments`,
        {
          method: 'PUT',
          body: JSON.stringify(data),
        }
      ),
  },

  // Department / Org Chart endpoints
  departments: {
    getTree: () =>
      fetchWithAuth<DepartmentsTreeResponse>('/admin/departments'),

    getDetail: (deptId: string) =>
      fetchWithAuth<DepartmentDetailResponse>(`/admin/departments/${deptId}`),

    create: (data: CreateDepartmentRequest) =>
      fetchWithAuth<DepartmentMutationResponse>('/admin/departments', {
        method: 'POST',
        body: JSON.stringify(data),
      }),

    update: (deptId: string, data: UpdateDepartmentRequest) =>
      fetchWithAuth<DepartmentMutationResponse>(
        `/admin/departments/${deptId}`,
        {
          method: 'PUT',
          body: JSON.stringify(data),
        }
      ),

    delete: (deptId: string) =>
      fetchWithAuth<DepartmentMutationResponse>(
        `/admin/departments/${deptId}`,
        { method: 'DELETE' }
      ),
  },

  // Phase 2: Goals
  goals: {
    getList: (params?: {
      status?: string;
      department_id?: string;
      period_type?: string;
      limit?: number;
      offset?: number;
    }) => {
      const searchParams = new URLSearchParams();
      if (params?.status) searchParams.set('status', params.status);
      if (params?.department_id) searchParams.set('department_id', params.department_id);
      if (params?.period_type) searchParams.set('period_type', params.period_type);
      if (params?.limit) searchParams.set('limit', String(params.limit));
      if (params?.offset) searchParams.set('offset', String(params.offset));
      const qs = searchParams.toString();
      return fetchWithAuth<import('@/types/api').GoalsListResponse>(
        `/admin/goals${qs ? `?${qs}` : ''}`
      );
    },

    getDetail: (goalId: string) =>
      fetchWithAuth<import('@/types/api').GoalDetailResponse>(`/admin/goals/${goalId}`),

    getStats: () =>
      fetchWithAuth<import('@/types/api').GoalStatsResponse>('/admin/goals/stats'),

    getForecast: () =>
      fetchWithAuth<import('@/types/api').GoalForecastResponse>('/admin/goals/forecast'),
  },

  // Phase 2: Wellness
  wellness: {
    getAlerts: (params?: {
      risk_level?: string;
      status?: string;
      limit?: number;
      offset?: number;
    }) => {
      const searchParams = new URLSearchParams();
      if (params?.risk_level) searchParams.set('risk_level', params.risk_level);
      if (params?.status) searchParams.set('status', params.status);
      if (params?.limit) searchParams.set('limit', String(params.limit));
      if (params?.offset) searchParams.set('offset', String(params.offset));
      const qs = searchParams.toString();
      return fetchWithAuth<import('@/types/api').EmotionAlertsResponse>(
        `/admin/wellness/alerts${qs ? `?${qs}` : ''}`
      );
    },

    getTrends: (params?: { days?: number; department_id?: string }) => {
      const searchParams = new URLSearchParams();
      if (params?.days) searchParams.set('days', String(params.days));
      if (params?.department_id) searchParams.set('department_id', params.department_id);
      const qs = searchParams.toString();
      return fetchWithAuth<import('@/types/api').EmotionTrendsResponse>(
        `/admin/wellness/trends${qs ? `?${qs}` : ''}`
      );
    },
  },

  // Phase 2: Tasks
  tasks: {
    getOverview: () =>
      fetchWithAuth<import('@/types/api').TaskOverviewStats>('/admin/tasks/overview'),

    getList: (params?: { source?: string; limit?: number; offset?: number }) => {
      const searchParams = new URLSearchParams();
      if (params?.source) searchParams.set('source', params.source);
      if (params?.limit) searchParams.set('limit', String(params.limit));
      if (params?.offset) searchParams.set('offset', String(params.offset));
      const qs = searchParams.toString();
      return fetchWithAuth<import('@/types/api').TaskListResponse>(
        `/admin/tasks/list${qs ? `?${qs}` : ''}`
      );
    },
  },

  // Phase 3: Insights
  insights: {
    getList: (params?: { importance?: string; status?: string; limit?: number; offset?: number }) => {
      const searchParams = new URLSearchParams();
      if (params?.importance) searchParams.set('importance', params.importance);
      if (params?.status) searchParams.set('status', params.status);
      if (params?.limit) searchParams.set('limit', String(params.limit));
      if (params?.offset) searchParams.set('offset', String(params.offset));
      const qs = searchParams.toString();
      return fetchWithAuth<import('@/types/api').InsightsListResponse>(
        `/admin/insights${qs ? `?${qs}` : ''}`
      );
    },

    getPatterns: (params?: { limit?: number }) => {
      const searchParams = new URLSearchParams();
      if (params?.limit) searchParams.set('limit', String(params.limit));
      const qs = searchParams.toString();
      return fetchWithAuth<import('@/types/api').QuestionPatternsResponse>(
        `/admin/insights/patterns${qs ? `?${qs}` : ''}`
      );
    },

    getWeeklyReports: (params?: { limit?: number }) => {
      const searchParams = new URLSearchParams();
      if (params?.limit) searchParams.set('limit', String(params.limit));
      const qs = searchParams.toString();
      return fetchWithAuth<import('@/types/api').WeeklyReportsResponse>(
        `/admin/insights/weekly-reports${qs ? `?${qs}` : ''}`
      );
    },
  },

  // Phase 3: Meetings
  meetings: {
    getList: (params?: { status?: string; limit?: number; offset?: number }) => {
      const searchParams = new URLSearchParams();
      if (params?.status) searchParams.set('status', params.status);
      if (params?.limit) searchParams.set('limit', String(params.limit));
      if (params?.offset) searchParams.set('offset', String(params.offset));
      const qs = searchParams.toString();
      return fetchWithAuth<import('@/types/api').MeetingsListResponse>(
        `/admin/meetings${qs ? `?${qs}` : ''}`
      );
    },
    getDetail: (meetingId: string) =>
      fetchWithAuth<import('@/types/api').MeetingDetailResponse>(
        `/admin/meetings/${meetingId}`
      ),
  },

  // Phase 3: Proactive
  proactive: {
    getActions: (params?: { trigger_type?: string; limit?: number; offset?: number }) => {
      const searchParams = new URLSearchParams();
      if (params?.trigger_type) searchParams.set('trigger_type', params.trigger_type);
      if (params?.limit) searchParams.set('limit', String(params.limit));
      if (params?.offset) searchParams.set('offset', String(params.offset));
      const qs = searchParams.toString();
      return fetchWithAuth<import('@/types/api').ProactiveActionsResponse>(
        `/admin/proactive/actions${qs ? `?${qs}` : ''}`
      );
    },

    getStats: () =>
      fetchWithAuth<import('@/types/api').ProactiveStatsResponse>('/admin/proactive/stats'),
  },

  // Phase 4: Teachings
  teachings: {
    getList: (params?: { category?: string; is_active?: boolean; limit?: number; offset?: number }) => {
      const searchParams = new URLSearchParams();
      if (params?.category) searchParams.set('category', params.category);
      if (params?.is_active !== undefined) searchParams.set('active_only', String(params.is_active));
      if (params?.limit) searchParams.set('limit', String(params.limit));
      if (params?.offset) searchParams.set('offset', String(params.offset));
      const qs = searchParams.toString();
      return fetchWithAuth<import('@/types/api').TeachingsListResponse>(
        `/admin/teachings${qs ? `?${qs}` : ''}`
      );
    },

    getConflicts: (params?: { limit?: number }) => {
      const searchParams = new URLSearchParams();
      if (params?.limit) searchParams.set('limit', String(params.limit));
      const qs = searchParams.toString();
      return fetchWithAuth<import('@/types/api').TeachingConflictsResponse>(
        `/admin/teachings/conflicts${qs ? `?${qs}` : ''}`
      );
    },

    getUsageStats: () =>
      fetchWithAuth<import('@/types/api').TeachingUsageStatsResponse>('/admin/teachings/usage-stats'),

    getPenetration: () =>
      fetchWithAuth<import('@/types/api').TeachingPenetrationResponse>('/admin/teachings/penetration'),
  },

  // Phase 4: System Health
  system: {
    getHealth: () =>
      fetchWithAuth<import('@/types/api').SystemHealthSummary>('/admin/system/health'),

    getMetrics: (params?: { days?: number }) => {
      const searchParams = new URLSearchParams();
      if (params?.days) searchParams.set('days', String(params.days));
      const qs = searchParams.toString();
      return fetchWithAuth<import('@/types/api').SystemMetricsResponse>(
        `/admin/system/metrics${qs ? `?${qs}` : ''}`
      );
    },

    getDiagnoses: (params?: { limit?: number }) => {
      const searchParams = new URLSearchParams();
      if (params?.limit) searchParams.set('limit', String(params.limit));
      const qs = searchParams.toString();
      return fetchWithAuth<import('@/types/api').SelfDiagnosesResponse>(
        `/admin/system/diagnoses${qs ? `?${qs}` : ''}`
      );
    },
  },

  // Emergency Stop
  emergencyStop: {
    getStatus: () =>
      fetchWithAuth<EmergencyStopStatusResponse>('/admin/emergency-stop/status'),

    activate: (reason: string) =>
      fetchWithAuth<EmergencyStopActionResponse>('/admin/emergency-stop/activate', {
        method: 'POST',
        body: JSON.stringify({ reason }),
      }),

    deactivate: () =>
      fetchWithAuth<EmergencyStopActionResponse>('/admin/emergency-stop/deactivate', {
        method: 'POST',
      }),
  },

  // ===== Zoom連携設定 =====
  zoomSettings: {
    getConfigs: () =>
      fetchWithAuth<{
        status: string;
        configs: Array<{
          id: string;
          meeting_name_pattern: string;
          chatwork_room_id: string;
          room_name: string | null;
          is_active: boolean;
          created_at: string | null;
          updated_at: string | null;
        }>;
        total: number;
      }>('/admin/zoom/configs'),

    createConfig: (data: {
      meeting_name_pattern: string;
      chatwork_room_id: string;
      room_name?: string;
      is_active?: boolean;
    }) =>
      fetchWithAuth<{ status: string; config: Record<string, unknown> }>('/admin/zoom/configs', {
        method: 'POST',
        body: JSON.stringify(data),
      }),

    updateConfig: (id: string, data: { is_active?: boolean; meeting_name_pattern?: string; chatwork_room_id?: string; room_name?: string }) =>
      fetchWithAuth<{ status: string; config: Record<string, unknown> }>(`/admin/zoom/configs/${id}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      }),

    deleteConfig: (id: string) =>
      fetchWithAuth<{ status: string }>(`/admin/zoom/configs/${id}`, {
        method: 'DELETE',
      }),
  },

  // ===== Zoomアカウント管理（複数アカウント対応） =====
  zoomAccounts: {
    getAccounts: () =>
      fetchWithAuth<{
        status: string;
        accounts: Array<{
          id: string;
          account_name: string;
          zoom_account_id: string;
          webhook_secret_token_masked: string;
          default_room_id: string | null;
          is_active: boolean;
          created_at: string | null;
          updated_at: string | null;
        }>;
        total: number;
      }>('/admin/zoom/accounts'),

    createAccount: (data: {
      account_name: string;
      zoom_account_id: string;
      webhook_secret_token: string;
      default_room_id?: string;
      is_active?: boolean;
    }) =>
      fetchWithAuth<{ status: string; account: Record<string, unknown> }>('/admin/zoom/accounts', {
        method: 'POST',
        body: JSON.stringify(data),
      }),

    updateAccount: (id: string, data: {
      account_name?: string;
      webhook_secret_token?: string;
      default_room_id?: string;
      is_active?: boolean;
    }) =>
      fetchWithAuth<{ status: string; account: Record<string, unknown> }>(`/admin/zoom/accounts/${id}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      }),

    deleteAccount: (id: string) =>
      fetchWithAuth<{ status: string }>(`/admin/zoom/accounts/${id}`, {
        method: 'DELETE',
      }),
  },

  // ===== 連携設定 =====
  integrations: {
    getGoogleCalendarStatus: () =>
      fetchWithAuth<{
        status: string;
        is_connected: boolean;
        google_email: string | null;
        connected_at: string | null;
        token_valid: boolean;
      }>('/admin/integrations/google-calendar/status'),

    getGoogleCalendarConnectUrl: () =>
      fetchWithAuth<{
        status: string;
        auth_url: string;
      }>('/admin/integrations/google-calendar/connect'),

    disconnectGoogleCalendar: () =>
      fetchWithAuth<{
        status: string;
        message: string;
      }>('/admin/integrations/google-calendar/disconnect', {
        method: 'POST',
      }),

    getCalendarEvents: (days: number = 14) =>
      fetchWithAuth<{
        status: string;
        calendar_id: string;
        events: Array<{
          id: string;
          summary: string;
          start: string;
          end: string;
          all_day: boolean;
          location: string | null;
          description: string | null;
          html_link: string | null;
        }>;
        total: number;
      }>(`/admin/integrations/google-calendar/events?days=${days}`),
  },
};
