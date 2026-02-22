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
const OrgChartPage = lazy(() =>
  import('@/pages/org-chart').then((m) => ({ default: m.OrgChartPage }))
);
const GoalsPage = lazy(() =>
  import('@/pages/goals').then((m) => ({ default: m.GoalsPage }))
);
const WellnessPage = lazy(() =>
  import('@/pages/wellness').then((m) => ({ default: m.WellnessPage }))
);
const TasksPage = lazy(() =>
  import('@/pages/tasks').then((m) => ({ default: m.TasksPage }))
);
const InsightsPage = lazy(() =>
  import('@/pages/insights').then((m) => ({ default: m.InsightsPage }))
);
const MeetingsPage = lazy(() =>
  import('@/pages/meetings').then((m) => ({ default: m.MeetingsPage }))
);
const ProactivePage = lazy(() =>
  import('@/pages/proactive').then((m) => ({ default: m.ProactivePage }))
);
const TeachingsPage = lazy(() =>
  import('@/pages/teachings').then((m) => ({ default: m.TeachingsPage }))
);
const IntegrationsPage = lazy(() =>
  import('@/pages/integrations').then((m) => ({ default: m.IntegrationsPage }))
);
const SystemPage = lazy(() =>
  import('@/pages/system').then((m) => ({ default: m.SystemPage }))
);
const MorningBriefingPage = lazy(() =>
  import('@/pages/morning-briefing').then((m) => ({ default: m.MorningBriefingPage }))
);
const ZoomSettingsPage = lazy(() =>
  import('@/pages/zoom-settings').then((m) => ({ default: m.ZoomSettingsPage }))
);
const GoogleDrivePage = lazy(() =>
  import('@/pages/google-drive').then((m) => ({ default: m.GoogleDrivePage }))
);
const CalendarPage = lazy(() =>
  import('@/pages/calendar').then((m) => ({ default: m.CalendarPage }))
);
const BrainLearningPage = lazy(() =>
  import('@/pages/brain-learning').then((m) => ({ default: m.BrainLearningPage }))
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

const orgChartRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/org-chart',
  component: () => <ProtectedRoute component={OrgChartPage} />,
});

const goalsRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/goals',
  component: () => <ProtectedRoute component={GoalsPage} />,
});

const wellnessRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/wellness',
  component: () => <ProtectedRoute component={WellnessPage} />,
});

const tasksRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/tasks',
  component: () => <ProtectedRoute component={TasksPage} />,
});

const insightsRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/insights',
  component: () => <ProtectedRoute component={InsightsPage} />,
});

const meetingsRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/meetings',
  component: () => <ProtectedRoute component={MeetingsPage} />,
});

const proactiveRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/proactive',
  component: () => <ProtectedRoute component={ProactivePage} />,
});

const teachingsRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/teachings',
  component: () => <ProtectedRoute component={TeachingsPage} />,
});

const integrationsRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/integrations',
  component: () => <ProtectedRoute component={IntegrationsPage} />,
});

const systemRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/system',
  component: () => <ProtectedRoute component={SystemPage} />,
});

const morningRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/morning',
  component: () => <ProtectedRoute component={MorningBriefingPage} />,
});

const zoomSettingsRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/zoom-settings',
  component: () => <ProtectedRoute component={ZoomSettingsPage} />,
});

const googleDriveRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/google-drive',
  component: () => <ProtectedRoute component={GoogleDrivePage} />,
});

const calendarRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/calendar',
  component: () => <ProtectedRoute component={CalendarPage} />,
});

const brainLearningRoute = new Route({
  getParentRoute: () => rootRoute,
  path: '/brain-learning',
  component: () => <ProtectedRoute component={BrainLearningPage} />,
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  indexRoute,
  orgChartRoute,
  goalsRoute,
  wellnessRoute,
  tasksRoute,
  brainRoute,
  brainLearningRoute,
  insightsRoute,
  meetingsRoute,
  proactiveRoute,
  teachingsRoute,
  costsRoute,
  integrationsRoute,
  systemRoute,
  membersRoute,
  morningRoute,
  zoomSettingsRoute,
  googleDriveRoute,
  calendarRoute,
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
