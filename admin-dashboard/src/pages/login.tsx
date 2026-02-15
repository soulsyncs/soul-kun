/**
 * Login page
 * Google OAuth login for admin users (Level 5+)
 * Falls back to token-based login when Google Client ID is not configured.
 */

import { useEffect, useCallback, useState } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { useAuth } from '@/hooks/use-auth';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ApiError } from '@/lib/api';

// Google Identity Services callback type
declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (response: { credential: string }) => void;
          }) => void;
          renderButton: (
            element: HTMLElement,
            config: {
              theme?: string;
              size?: string;
              width?: number;
              text?: string;
            }
          ) => void;
        };
      };
    };
  }
}

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';

export function LoginPage() {
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [tokenInput, setTokenInput] = useState('');
  const { loginWithGoogle, loginWithToken, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      navigate({ to: '/' });
    }
  }, [isAuthenticated, navigate]);

  const handleGoogleCallback = useCallback(
    async (response: { credential: string }) => {
      setError('');
      setIsLoading(true);
      try {
        await loginWithGoogle(response.credential);
        navigate({ to: '/' });
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.status === 401 || err.status === 403) {
            setError('アクセスが拒否されました。権限を確認してください。');
          } else if (err.status >= 500) {
            setError('サーバーエラーが発生しました。しばらくしてからお試しください。');
          } else {
            setError('ログインに失敗しました。もう一度お試しください。');
          }
        } else {
          setError('予期しないエラーが発生しました');
        }
      } finally {
        setIsLoading(false);
      }
    },
    [loginWithGoogle, navigate]
  );

  const handleTokenLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = tokenInput.trim();
    if (!trimmed) {
      setError('トークンを入力してください');
      return;
    }
    setError('');
    setIsLoading(true);
    try {
      await loginWithToken(trimmed);
      navigate({ to: '/' });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          setError('トークンが無効または期限切れです');
        } else if (err.status === 403) {
          setError('管理者権限（Level 5以上）が必要です');
        } else {
          setError('ログインに失敗しました');
        }
      } else {
        setError('予期しないエラーが発生しました');
      }
    } finally {
      setIsLoading(false);
    }
  };

  // Initialize Google Identity Services
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;

    const initGoogle = () => {
      if (!window.google) return;

      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: handleGoogleCallback,
      });

      const buttonEl = document.getElementById('google-signin-button');
      if (buttonEl) {
        window.google.accounts.id.renderButton(buttonEl, {
          theme: 'outline',
          size: 'large',
          width: 360,
          text: 'signin_with',
        });
      }
    };

    // Load GIS script if not already loaded
    if (window.google) {
      initGoogle();
    } else {
      const script = document.createElement('script');
      script.src = 'https://accounts.google.com/gsi/client';
      script.async = true;
      script.defer = true;
      script.onload = initGoogle;
      document.head.appendChild(script);
    }
  }, [handleGoogleCallback]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/50">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1 text-center">
          <CardTitle className="text-2xl font-bold">ソウルくん管理画面</CardTitle>
          <CardDescription>
            {GOOGLE_CLIENT_ID
              ? 'Googleアカウントでログインしてください'
              : 'アクセストークンを入力してログイン'}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-4">
          {/* Google Sign-In button (when configured) */}
          {GOOGLE_CLIENT_ID ? (
            <div id="google-signin-button" />
          ) : (
            /* Token-based login (fallback) */
            <form onSubmit={handleTokenLogin} className="w-full space-y-3">
              <textarea
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder="JWTトークン"
                rows={3}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                disabled={isLoading}
              />
              <button
                type="submit"
                disabled={isLoading || !tokenInput.trim()}
                className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoading ? '認証中...' : 'ログイン'}
              </button>
            </form>
          )}

          {isLoading && GOOGLE_CLIENT_ID && (
            <p className="text-sm text-muted-foreground animate-pulse">
              認証中...
            </p>
          )}

          {error && (
            <div className="w-full rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}

          <p className="text-xs text-muted-foreground text-center mt-4">
            レベル5以上の管理者のみアクセスできます
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
