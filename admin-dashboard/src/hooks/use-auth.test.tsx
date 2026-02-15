/**
 * Tests for useAuth hook
 * Verifies login, logout, cache clearing
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { AuthProvider, useAuth } from './use-auth';
import { ApiError } from '@/lib/api';

// Mock the api module
vi.mock('@/lib/api', () => ({
  api: {
    auth: {
      me: vi.fn(),
      loginWithGoogle: vi.fn(),
      logout: vi.fn().mockResolvedValue(undefined),
    },
  },
  ApiError: class extends Error {
    public status: number;
    constructor(message: string, status: number) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
    }
  },
  setBearerToken: vi.fn(),
  clearBearerToken: vi.fn(),
}));

import { api } from '@/lib/api';

const mockedApi = vi.mocked(api);

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    );
  };
}

describe('useAuth', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('starts with loading state', () => {
    mockedApi.auth.me.mockReturnValue(new Promise(() => {})); // never resolves
    const { result } = renderHook(() => useAuth(), {
      wrapper: createWrapper(),
    });
    expect(result.current.isLoading).toBe(true);
    expect(result.current.isAuthenticated).toBe(false);
  });

  it('sets user after successful me() call', async () => {
    const mockUser = {
      user_id: 'u1',
      organization_id: 'org1',
      name: 'Test',
      email: 'test@example.com',
      role: 'admin',
      role_level: 5,
      department_id: null,
    };
    mockedApi.auth.me.mockResolvedValueOnce(mockUser);

    const { result } = renderHook(() => useAuth(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.user?.name).toBe('Test');
  });

  it('sets user to null on 401', async () => {
    mockedApi.auth.me.mockRejectedValueOnce(
      new ApiError('Unauthorized', 401)
    );

    const { result } = renderHook(() => useAuth(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
  });

  it('logout clears user', async () => {
    const mockUser = {
      user_id: 'u1',
      organization_id: 'org1',
      name: 'Test',
      email: null,
      role: null,
      role_level: 5,
      department_id: null,
    };
    mockedApi.auth.me.mockResolvedValueOnce(mockUser);

    const { result } = renderHook(() => useAuth(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isAuthenticated).toBe(true);
    });

    await act(async () => {
      await result.current.logout();
    });

    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
  });
});
