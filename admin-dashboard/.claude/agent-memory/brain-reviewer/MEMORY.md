# brain-reviewer Agent Memory

## Scope: admin-dashboard (frontend only)
This reviewer covers `admin-dashboard/src/` — React/TypeScript/Tailwind.
Backend lib/brain/ rules (organization_id, RLS, audit logs) do NOT apply here
because admin-dashboard is a read-only management UI (CLAUDE.md §1-1 exception).
Only the following CLAUDE.md rules directly apply to this scope:
- §3-2 checklist items: 1 (logic bugs), 2 (XSS/security), 4 (test coverage), 8 (PII in errors), 16 (hardcoded values)
- Brain bypass rule does NOT apply (§1-1 exemption)
- organization_id / RLS / audit log rules do NOT apply (frontend only)

## Recurring patterns found in admin-dashboard

### TypeScript type safety
- `TaskOverviewStats.chatwork_tasks` is NON-OPTIONAL in api.ts (line 405) but the
  component authors treated it as optional (taskStats?.chatwork_tasks?.overdue).
  This is actually CORRECT defensively because `taskStats` itself can be undefined
  while the query is loading. The inner optional chain is technically redundant per
  the type definition but harmless. Do NOT flag as a bug.
- `AiRoiResponse.roi_multiplier` is typed as `number` (non-optional). The `?? 0`
  fallback in costs.tsx (line 434) is redundant but harmless.

### Mobile responsive gaps (known issue as of 2026-02-20 review)
- goals.tsx line 260: `flex gap-6` + `w-80 shrink-0` detail panel — NOT made
  responsive. On mobile, the 320px fixed-width side panel will overflow on small
  screens. This was NOT fixed in this PR despite members.tsx being fixed.
- costs.tsx line 418: `grid grid-cols-3` ROI card — no md: breakpoint. Three
  columns will be cramped at 390px. Minor but worth flagging.

### Navigation: raw <a href> vs <Link> inconsistency
- dashboard.tsx line 288 uses raw `<a href="/tasks">` instead of TanStack Router
  `<Link to="/tasks">`. This causes a full page reload and breaks SPA navigation.
  All other pages use `<Link>` from @tanstack/react-router correctly.

### Accessibility gaps
- app-layout.tsx hamburger button: missing `aria-expanded={sidebarOpen}` and
  `aria-controls` attribute referencing the sidebar element.
- sidebar.tsx: nav element missing `aria-label` (e.g., aria-label="メインナビゲーション").

### z-index stacking in app-layout
- Overlay: z-20, Sidebar: z-30 — correct order.
- `md:z-auto` on sidebar wrapper resets z-index on desktop — correct.

## Files reviewed on 2026-02-20
- src/components/layout/app-layout.tsx
- src/components/layout/sidebar.tsx
- src/pages/morning-briefing.tsx
- src/pages/dashboard.tsx
- src/pages/costs.tsx
- src/pages/members.tsx
- src/pages/goals.tsx
