/**
 * Login page
 * Google OAuth login for admin users (Level 5+)
 *
 * For MVP, shows a "Sign in with Google" button.
 * Google Identity Services (GIS) will be loaded from CDN.
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
  const { loginWithGoogle, isAuthenticated } = useAuth();
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
            setError('Access denied. Please check your permissions.');
          } else if (err.status >= 500) {
            setError('Server error. Please try again later.');
          } else {
            setError('Login failed. Please try again.');
          }
        } else {
          setError('An unexpected error occurred');
        }
      } finally {
        setIsLoading(false);
      }
    },
    [loginWithGoogle, navigate]
  );

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
          <CardTitle className="text-2xl font-bold">Soul-kun Admin</CardTitle>
          <CardDescription>
            Sign in with your Google account to access the dashboard
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-4">
          {/* Google Sign-In button */}
          {GOOGLE_CLIENT_ID ? (
            <div id="google-signin-button" />
          ) : (
            <p className="text-sm text-muted-foreground text-center">
              Google Client ID not configured.
              <br />
              Set VITE_GOOGLE_CLIENT_ID in .env
            </p>
          )}

          {isLoading && (
            <p className="text-sm text-muted-foreground animate-pulse">
              Authenticating...
            </p>
          )}

          {error && (
            <div className="w-full rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}

          <p className="text-xs text-muted-foreground text-center mt-4">
            Access restricted to Level 5+ administrators only
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
