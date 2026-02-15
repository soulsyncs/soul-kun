/**
 * Tests for API client
 * Verifies endpoint paths, query params, error handling
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api, ApiError } from './api';

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// Mock import.meta.env
vi.stubGlobal('import', { meta: { env: { VITE_API_URL: '' } } });

function mockJsonResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: () => Promise.resolve(data),
  };
}

describe('API Client', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('fetchWithAuth', () => {
    it('includes credentials: include for cookie auth', async () => {
      mockFetch.mockResolvedValueOnce(mockJsonResponse({ user_id: '1' }));

      await api.auth.me();

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ credentials: 'include' })
      );
    });

    it('sets Content-Type and CSRF headers', async () => {
      mockFetch.mockResolvedValueOnce(mockJsonResponse({ user_id: '1' }));

      await api.auth.me();

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
          }),
        })
      );
    });

    it('throws ApiError on non-ok response', async () => {
      mockFetch.mockResolvedValueOnce(
        mockJsonResponse({ detail: 'Unauthorized' }, 401)
      );

      await expect(api.auth.me()).rejects.toThrow(ApiError);
    });

    it('extracts error_message from detail object', async () => {
      mockFetch.mockResolvedValueOnce(
        mockJsonResponse(
          { detail: { error_message: 'Access denied' } },
          403
        )
      );

      try {
        await api.auth.me();
      } catch (error) {
        expect(error).toBeInstanceOf(ApiError);
        expect((error as ApiError).message).toBe('Access denied');
        expect((error as ApiError).status).toBe(403);
      }
    });

    it('extracts string detail message', async () => {
      mockFetch.mockResolvedValueOnce(
        mockJsonResponse({ detail: 'Not found' }, 404)
      );

      try {
        await api.auth.me();
      } catch (error) {
        expect(error).toBeInstanceOf(ApiError);
        expect((error as ApiError).message).toBe('Not found');
      }
    });
  });

  describe('endpoint paths', () => {
    it('auth.me calls /admin/auth/me', async () => {
      mockFetch.mockResolvedValueOnce(mockJsonResponse({ user_id: '1' }));
      await api.auth.me();
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/admin/auth/me'),
        expect.any(Object)
      );
    });

    it('auth.loginWithGoogle sends POST with id_token', async () => {
      mockFetch.mockResolvedValueOnce(
        mockJsonResponse({ access_token: 'tok', token_type: 'bearer', expires_in: 3600 })
      );
      await api.auth.loginWithGoogle('test-token');
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/admin/auth/google'),
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ id_token: 'test-token' }),
        })
      );
    });

    it('dashboard.getSummary includes period param', async () => {
      mockFetch.mockResolvedValueOnce(mockJsonResponse({ status: 'ok', kpis: {} }));
      await api.dashboard.getSummary('7d');
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/admin/dashboard/summary?period=7d'),
        expect.any(Object)
      );
    });

    it('brain.getMetrics includes days param', async () => {
      mockFetch.mockResolvedValueOnce(mockJsonResponse({ status: 'ok', metrics: [] }));
      await api.brain.getMetrics(14);
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/admin/brain/metrics?days=14'),
        expect.any(Object)
      );
    });

    it('brain.getLogs includes limit and offset params', async () => {
      mockFetch.mockResolvedValueOnce(mockJsonResponse({ status: 'ok', logs: [] }));
      await api.brain.getLogs(20, 10);
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/admin/brain/logs'),
        expect.any(Object)
      );
      const url = mockFetch.mock.calls[0][0] as string;
      expect(url).toContain('limit=20');
      expect(url).toContain('offset=10');
    });

    it('costs.getDaily includes days param', async () => {
      mockFetch.mockResolvedValueOnce(mockJsonResponse({ status: 'ok', daily: [] }));
      await api.costs.getDaily(7);
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/admin/costs/daily?days=7'),
        expect.any(Object)
      );
    });

    it('costs.getMonthly calls correct path', async () => {
      mockFetch.mockResolvedValueOnce(mockJsonResponse({ status: 'ok', months: [] }));
      await api.costs.getMonthly();
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/admin/costs/monthly'),
        expect.any(Object)
      );
    });

    it('costs.getBreakdown includes days param', async () => {
      mockFetch.mockResolvedValueOnce(mockJsonResponse({ status: 'ok' }));
      await api.costs.getBreakdown(30);
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/admin/costs/breakdown?days=30'),
        expect.any(Object)
      );
    });

    it('members.getList includes search param', async () => {
      mockFetch.mockResolvedValueOnce(mockJsonResponse({ status: 'ok', members: [] }));
      await api.members.getList({ search: 'test', limit: 20, offset: 0 });
      const url = mockFetch.mock.calls[0][0] as string;
      expect(url).toContain('/admin/members');
      expect(url).toContain('search=test');
      expect(url).toContain('limit=20');
      expect(url).toContain('offset=0');
    });

    it('members.getList omits undefined params', async () => {
      mockFetch.mockResolvedValueOnce(mockJsonResponse({ status: 'ok', members: [] }));
      await api.members.getList({ limit: 20, offset: 0 });
      const url = mockFetch.mock.calls[0][0] as string;
      expect(url).not.toContain('search');
    });

    it('members.getDetail includes userId in path', async () => {
      mockFetch.mockResolvedValueOnce(mockJsonResponse({ user_id: 'abc' }));
      await api.members.getDetail('abc-123');
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/admin/members/abc-123'),
        expect.any(Object)
      );
    });
  });
});
