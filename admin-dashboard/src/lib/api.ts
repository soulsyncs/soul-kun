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
  MembersListResponse,
  MemberResponse,
} from '@/types/api';

const API_BASE_URL =
  import.meta.env.VITE_API_URL || 'http://localhost:8080/api/v1';

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
let _bearerToken: string | null = null;

export function setBearerToken(token: string) {
  _bearerToken = token;
}

export function clearBearerToken() {
  _bearerToken = null;
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
  },
};
