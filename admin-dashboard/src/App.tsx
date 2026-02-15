/**
 * Main App component with routing
 * Uses React.lazy for code splitting to reduce initial bundle
 */

import { lazy, Suspense } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Router, Route, RootRoute, RouterProvider, Navigate } from '@tanstack/react-router';
import { AuthProvider, useAuth } from '@/hooks/use-auth';
import { TooltipProvider } from '@/components/ui/tooltip';
import { LoginPage } from '@/pages/login';

// Lazy-loaded pages (code splitting)
const DashboardPage = lazy(() =>
  import('@/pages/dashboard').then((m) => ({ default: m.DashboardPage }))
);
const BrainPage = lazy(() =>
  import('@/pages/brain').then((m) => ({ default: m.BrainPage }))
);
const CostsPage = lazy(() =>
  import('@/pages/costs').then((m) => ({ default: m.CostsPage }))
);
const MembersPage = lazy(() =>
  import('@/pages/members').then((m) => ({ default: m.MembersPage }))
);

// Loading fallback
function PageLoader() {
  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="animate-pulse text-muted-foreground">読み込み中...</div>
    </div>
  );
}

// Create a query client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 300000, // 5 minutes (CLAUDE.md Rule #6)
      refetchOnWindowFocus: true,
    },
  },
});

// Create route tree
const rootRoute = new RootRoute();

const loginRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/login',
  component: LoginPage,
});

// Protected route wrapper
function ProtectedRoute({ component: Component }: { component: React.ComponentType }) {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return <PageLoader />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" />;
  }

  return (
    <Suspense fallback={<PageLoader />}>
      <Component />
    </Suspense>
  );
}

const indexRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/',
  component: () => <ProtectedRoute component={DashboardPage} />,
});

const brainRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/brain',
  component: () => <ProtectedRoute component={BrainPage} />,
});

const costsRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/costs',
  component: () => <ProtectedRoute component={CostsPage} />,
});

const membersRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/members',
  component: () => <ProtectedRoute component={MembersPage} />,
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  indexRoute,
  brainRoute,
  costsRoute,
  membersRoute,
]);

const router = new Router({ routeTree });

// Register router for type safety
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
