/**
 * Authentication context and hook
 * Uses Google OAuth → backend JWT flow (httpOnly cookies)
 */

import {
  createContext,
  useContext,
  useState,
  useEffect,
  type ReactNode,
} from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, ApiError, setBearerToken, clearBearerToken } from '@/lib/api';
import type { AuthMeResponse } from '@/types/api';

interface AuthContextType {
  user: AuthMeResponse | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  loginWithGoogle: (idToken: string) => Promise<void>;
  loginWithToken: (token: string) => Promise<void>;
  logout: () => Promise<void>;
  refetch: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<AuthMeResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchUser = async () => {
    try {
      setIsLoading(true);
      const response = await api.auth.me();
      setUser(response);
    } catch (error) {
      setUser(null);
      if (!(error instanceof ApiError && error.status === 401)) {
        // Non-auth error — user simply not logged in, no action needed
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchUser();
  }, []);

  const loginWithGoogle = async (idToken: string) => {
    const res = await api.auth.loginWithGoogle(idToken);
    if (res.access_token) {
      setBearerToken(res.access_token);
    }
    await fetchUser();
  };

  const loginWithToken = async (token: string) => {
    setBearerToken(token);
    await api.auth.loginWithToken(token);
    await fetchUser();
  };

  const logout = async () => {
    try {
      await api.auth.logout();
    } catch {
      // best effort — cookie may already be expired
    }
    clearBearerToken();
    queryClient.clear();
    setUser(null);
  };

  const value: AuthContextType = {
    user,
    isLoading,
    isAuthenticated: user !== null,
    loginWithGoogle,
    loginWithToken,
    logout,
    refetch: fetchUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
