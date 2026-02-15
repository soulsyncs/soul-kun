# Soul-kun Admin Dashboard - Design Document

## Architecture Overview

### System Components

```
┌─────────────┐     HTTPS      ┌──────────────┐     Private    ┌─────────────┐
│   Browser   │ ─────────────> │   Vercel     │ ──────────────> │  Cloud Run  │
│  (React UI) │                │   Frontend   │                 │  FastAPI    │
└─────────────┘                └──────────────┘                 └─────────────┘
                                                                        │
                                                                        │ SQL
                                                                        ▼
                                                                 ┌─────────────┐
                                                                 │  Cloud SQL  │
                                                                 │  PostgreSQL │
                                                                 └─────────────┘
```

### Technology Stack

**Frontend (Vercel)**
- React 18 + TypeScript 5
- Vite 6 (build tool)
- Tailwind CSS 4 (styling)
- shadcn/ui (component library)
- TanStack Router (routing)
- TanStack Query (data fetching, caching)
- Recharts (visualization)
- Lucide React (icons)

**Backend (Cloud Run)**
- FastAPI (Python 3.11+)
- Pydantic v2 (validation)
- asyncpg (PostgreSQL async driver)
- python-jose (JWT)
- passlib (password hashing)

**Database**
- Cloud SQL PostgreSQL 14
- Database: `soulkun_tasks`
- Existing schema (no migrations needed for Phase 1)

**Deployment**
- Frontend: Vercel (auto-deploy from `admin-dashboard/` directory)
- Backend: Cloud Run (asia-northeast1)
- DNS: Custom domain via Vercel

## Security Architecture

### Authentication Flow

1. **Login**: POST `/api/v1/auth/login` with email + password
2. **Response**: Set httpOnly cookie with JWT (7-day expiry)
3. **Requests**: Cookie automatically sent on all API calls
4. **Logout**: POST `/api/v1/auth/logout` clears cookie

### Security Decisions

| Decision | Rationale |
|----------|-----------|
| **httpOnly cookie for JWT** | Prevents XSS attacks. More secure than localStorage. |
| **CORS whitelist** | Only allow Vercel domain + localhost (dev). No `*` wildcards. |
| **SameSite=Lax** | CSRF protection while allowing normal navigation. |
| **Secure flag in prod** | Enforce HTTPS for cookie transmission. |
| **PII aggregation only** | Never expose raw ChatWork messages. Only metrics/counts. |
| **Organization isolation** | All queries filtered by `organization_id` (Rule #1). |
| **Password hashing** | bcrypt with salt (via passlib). |
| **JWT signing** | HS256 with 256-bit secret from Google Secret Manager. |

### PII Protection Rules

**Forbidden**:
- Raw ChatWork messages
- Individual user names in logs
- Email addresses in responses (except current user)

**Allowed**:
- Aggregated metrics (e.g., "20 conversations today")
- De-identified counts per member (member_id only)
- Cost totals (no message content)

## Phase 1 MVP Scope

### 5 Core Screens

| Screen | Path | Description |
|--------|------|-------------|
| **Login** | `/login` | Email + password form. Redirect to dashboard on success. |
| **Dashboard** | `/` | 6 KPI cards + 2 charts (7-day trends). |
| **Brain Analytics** | `/brain` | LLM usage: model distribution, conversation counts, response times. |
| **Cost Tracking** | `/costs` | Daily spend table + monthly trend chart. Budget alerts. |
| **Members** | `/members` | Member list with usage stats. Search/filter. |

### 10 API Endpoints

#### Authentication
- `POST /api/v1/auth/login` - Login with email/password
- `POST /api/v1/auth/logout` - Clear auth cookie
- `GET /api/v1/auth/me` - Get current user info

#### Dashboard
- `GET /api/v1/dashboard/kpis` - 6 KPI metrics (7-day period)
- `GET /api/v1/dashboard/trends` - Daily data for charts

#### Brain Analytics
- `GET /api/v1/brain/models` - Model usage distribution
- `GET /api/v1/brain/conversations` - Conversation counts by day

#### Cost Tracking
- `GET /api/v1/costs/daily` - Daily cost breakdown
- `GET /api/v1/costs/monthly` - Monthly trend

#### Members
- `GET /api/v1/members` - Member list with stats

### API Endpoint Specifications

#### `POST /api/v1/auth/login`

**Request**:
```json
{
  "email": "kazu@soulsyncx.com",
  "password": "secure_password"
}
```

**Response** (200):
```json
{
  "user": {
    "id": "uuid",
    "email": "kazu@soulsyncx.com",
    "role": "admin",
    "organization_id": "5f98365f-e7c5-4f48-9918-7fe9aabae5df"
  }
}
```
**Sets Cookie**: `auth_token=<jwt>; HttpOnly; Secure; SameSite=Lax; Max-Age=604800`

**Errors**:
- 401: Invalid credentials
- 422: Validation error

---

#### `GET /api/v1/auth/me`

**Headers**: Cookie with JWT (automatic)

**Response** (200):
```json
{
  "user": {
    "id": "uuid",
    "email": "kazu@soulsyncx.com",
    "role": "admin",
    "organization_id": "5f98365f-e7c5-4f48-9918-7fe9aabae5df"
  }
}
```

**Errors**:
- 401: Unauthorized (invalid/expired token)

---

#### `GET /api/v1/dashboard/kpis`

**Query Params**:
- `days` (optional, default=7): Number of days to analyze

**Response** (200):
```json
{
  "period": {
    "start": "2026-02-08T00:00:00Z",
    "end": "2026-02-15T00:00:00Z",
    "days": 7
  },
  "kpis": {
    "total_conversations": 142,
    "total_messages": 1247,
    "brain_calls": 856,
    "total_cost_usd": 28.45,
    "avg_response_time_seconds": 2.3,
    "active_members": 12
  },
  "changes": {
    "conversations_change_pct": 15.2,
    "messages_change_pct": 8.7,
    "brain_calls_change_pct": 22.1,
    "cost_change_pct": -5.3,
    "response_time_change_pct": -12.4,
    "members_change_pct": 0
  }
}
```

**Notes**:
- `changes` are vs. previous period (e.g., previous 7 days)
- Positive % = increase, negative % = decrease

---

#### `GET /api/v1/dashboard/trends`

**Query Params**:
- `days` (optional, default=7): Number of days

**Response** (200):
```json
{
  "daily_data": [
    {
      "date": "2026-02-08",
      "conversations": 18,
      "brain_calls": 112,
      "cost_usd": 3.21
    },
    {
      "date": "2026-02-09",
      "conversations": 23,
      "brain_calls": 145,
      "cost_usd": 4.67
    }
    // ... 5 more days
  ]
}
```

---

#### `GET /api/v1/brain/models`

**Query Params**:
- `start_date` (optional): ISO date (default: 7 days ago)
- `end_date` (optional): ISO date (default: today)

**Response** (200):
```json
{
  "period": {
    "start": "2026-02-08",
    "end": "2026-02-15"
  },
  "model_usage": [
    {
      "model_name": "claude-opus-4-6",
      "call_count": 524,
      "total_cost_usd": 18.92,
      "avg_response_time_seconds": 2.1,
      "percentage": 61.2
    },
    {
      "model_name": "gpt-4o",
      "call_count": 241,
      "total_cost_usd": 6.73,
      "avg_response_time_seconds": 1.8,
      "percentage": 28.2
    },
    {
      "model_name": "gemini-2.0-flash-exp",
      "call_count": 91,
      "total_cost_usd": 2.80,
      "avg_response_time_seconds": 1.5,
      "percentage": 10.6
    }
  ],
  "total_calls": 856
}
```

---

#### `GET /api/v1/brain/conversations`

**Query Params**:
- `days` (optional, default=7): Number of days

**Response** (200):
```json
{
  "daily_conversations": [
    {
      "date": "2026-02-08",
      "count": 18,
      "unique_members": 8
    },
    {
      "date": "2026-02-09",
      "count": 23,
      "unique_members": 10
    }
    // ... 5 more days
  ],
  "total_conversations": 142,
  "total_unique_members": 12
}
```

---

#### `GET /api/v1/costs/daily`

**Query Params**:
- `start_date` (optional): ISO date (default: 30 days ago)
- `end_date` (optional): ISO date (default: today)
- `limit` (optional, default=30): Max rows

**Response** (200):
```json
{
  "daily_costs": [
    {
      "date": "2026-02-14",
      "total_cost_usd": 5.23,
      "brain_cost_usd": 4.89,
      "other_cost_usd": 0.34,
      "call_count": 134
    },
    {
      "date": "2026-02-13",
      "total_cost_usd": 4.67,
      "brain_cost_usd": 4.21,
      "other_cost_usd": 0.46,
      "call_count": 121
    }
    // ... up to 30 days
  ],
  "total_cost_usd": 156.78,
  "avg_daily_cost_usd": 5.23
}
```

---

#### `GET /api/v1/costs/monthly`

**Query Params**:
- `months` (optional, default=6): Number of months

**Response** (200):
```json
{
  "monthly_costs": [
    {
      "year": 2026,
      "month": 2,
      "total_cost_usd": 89.45,
      "days_in_month": 28,
      "avg_daily_cost_usd": 3.19
    },
    {
      "year": 2026,
      "month": 1,
      "total_cost_usd": 124.67,
      "days_in_month": 31,
      "avg_daily_cost_usd": 4.02
    }
    // ... up to 6 months
  ],
  "budget": {
    "monthly_limit_usd": 200.00,
    "current_month_spend_usd": 89.45,
    "current_month_percentage": 44.7,
    "projected_month_end_usd": 157.82,
    "is_over_budget": false
  }
}
```

---

#### `GET /api/v1/members`

**Query Params**:
- `search` (optional): Filter by name/email
- `sort_by` (optional, default=name): Sort field (name, message_count, last_active)
- `order` (optional, default=asc): Sort order (asc, desc)
- `limit` (optional, default=50): Max results

**Response** (200):
```json
{
  "members": [
    {
      "id": "uuid",
      "name": "田中 太郎",
      "email": "tanaka@example.com",
      "role": "member",
      "is_active": true,
      "stats": {
        "total_messages": 234,
        "total_conversations": 45,
        "last_active_at": "2026-02-14T15:32:00Z",
        "avg_response_time_seconds": 2.1
      }
    }
    // ... more members
  ],
  "total_count": 12,
  "page": 1,
  "limit": 50
}
```

---

## Data Sources (Existing Tables)

All queries filtered by `organization_id = '5f98365f-e7c5-4f48-9918-7fe9aabae5df'` (Rule #1).

### `conversations`
- Columns: `id`, `organization_id`, `created_at`, `updated_at`, `status`
- Used for: Total conversation counts, daily trends

### `brain_analytics`
- Columns: `id`, `organization_id`, `timestamp`, `model_name`, `cost_usd`, `response_time_seconds`
- Used for: Model usage, cost tracking, response times

### `members` (or `users`)
- Columns: `id`, `organization_id`, `name`, `email`, `role`, `is_active`, `last_active_at`
- Used for: Member list, active member counts

### `messages` (if exists)
- Columns: `id`, `conversation_id`, `member_id`, `created_at`
- Used for: Message counts per member

**Note**: If tables don't exist, Phase 1 can use mock data. Phase 2 will create/migrate schemas.

---

## Frontend Structure

### Directory Layout

```
admin-dashboard/
├── public/
│   └── favicon.ico
├── src/
│   ├── main.tsx                   # App entry point
│   ├── index.css                  # Tailwind imports
│   ├── App.tsx                    # Router setup
│   ├── lib/
│   │   ├── api.ts                 # Fetch wrapper with auth
│   │   └── utils.ts               # cn() helper
│   ├── hooks/
│   │   ├── use-auth.ts            # Auth context/hook
│   │   └── use-query-params.ts    # URL query helpers
│   ├── components/
│   │   ├── ui/                    # shadcn components
│   │   ├── layout/
│   │   │   ├── sidebar.tsx        # Navigation sidebar
│   │   │   └── app-layout.tsx     # Main layout wrapper
│   │   └── dashboard/
│   │       ├── kpi-card.tsx       # Metric card with trend
│   │       ├── trend-chart.tsx    # Line chart component
│   │       └── cost-table.tsx     # Daily cost table
│   ├── pages/
│   │   ├── login.tsx              # Login page
│   │   ├── dashboard.tsx          # Dashboard page
│   │   ├── brain.tsx              # Brain analytics
│   │   ├── costs.tsx              # Cost tracking
│   │   └── members.tsx            # Member list
│   └── types/
│       └── api.ts                 # API response types
├── .env.example
├── .gitignore
├── package.json
├── tsconfig.json
├── vite.config.ts
└── DESIGN.md (this file)
```

### Component Examples

**KPI Card** (with trend indicator):
```tsx
<KpiCard
  title="Total Conversations"
  value={142}
  change={15.2}
  trend="up"
  icon={<MessageSquare />}
/>
```

**Trend Chart** (7-day line chart):
```tsx
<TrendChart
  data={dailyData}
  xKey="date"
  lines={[
    { key: "conversations", color: "#8b5cf6" },
    { key: "brain_calls", color: "#3b82f6" }
  ]}
/>
```

### Routing Strategy

**TanStack Router** (file-based routing):
- `/login` → `pages/login.tsx`
- `/` → `pages/dashboard.tsx`
- `/brain` → `pages/brain.tsx`
- `/costs` → `pages/costs.tsx`
- `/members` → `pages/members.tsx`

**Protected Routes**:
- All routes except `/login` require auth
- If not authenticated, redirect to `/login`
- After login, redirect to `/` (dashboard)

### State Management

**TanStack Query** for server state:
- Cache API responses (staleTime: 60s)
- Auto-refetch on window focus
- Optimistic updates for mutations

**React Context** for auth state:
- `useAuth()` hook provides `user`, `login()`, `logout()`
- Stored in memory (not localStorage)
- Revalidate on mount via `GET /api/v1/auth/me`

---

## Deployment Plan

### Phase 1 (MVP - Week 1)
1. **Backend**: Deploy FastAPI to Cloud Run (new service: `soul-kun-admin-api`)
2. **Frontend**: Deploy to Vercel (auto-deploy from `main` branch)
3. **Database**: Use existing Cloud SQL (`soulkun_tasks`)
4. **Secrets**: Store JWT secret in Google Secret Manager
5. **CORS**: Whitelist Vercel domain + localhost

### Environment Variables

**Backend (Cloud Run)**:
```bash
DATABASE_URL=postgresql+asyncpg://soulkun_user:***@127.0.0.1:5433/soulkun_tasks
JWT_SECRET_KEY=<from-secret-manager>
ALLOWED_ORIGINS=https://admin.soulsyncx.com,http://localhost:5173
ENVIRONMENT=production
```

**Frontend (Vercel)**:
```bash
VITE_API_URL=https://soul-kun-admin-api-xyz.a.run.app/api/v1
```

### DNS Setup
- Add CNAME: `admin.soulsyncx.com` → Vercel
- SSL cert auto-provisioned by Vercel

---

## Testing Strategy

### Backend Tests
- Unit tests: `pytest tests/` (auth, query logic)
- Integration tests: Real Cloud SQL Proxy connection
- E2E tests: Playwright (login → dashboard navigation)

### Frontend Tests
- Unit tests: Vitest + React Testing Library
- Component tests: Storybook (optional Phase 2)
- E2E tests: Playwright (critical paths only)

**Coverage Target**: 80% for backend logic, 60% for frontend components

---

## Performance Targets

| Metric | Target |
|--------|--------|
| **API Response Time** | < 500ms (p95) |
| **Frontend FCP** | < 1.5s |
| **Frontend TTI** | < 3s |
| **Database Query Time** | < 200ms (p95) |

**Optimization Strategies**:
- Database: Indexes on `organization_id`, `created_at`, `timestamp`
- Backend: Connection pooling (max 5 connections)
- Frontend: Code splitting, lazy loading routes
- CDN: Vercel Edge Network for static assets

---

## Monitoring & Logging

**Backend**:
- Cloud Run logs (structured JSON)
- Error tracking: Google Cloud Error Reporting
- Metrics: Request count, latency, error rate

**Frontend**:
- Vercel Analytics (Web Vitals)
- Error tracking: Sentry (Phase 2)

**Database**:
- Cloud SQL Insights (slow queries)
- Connection pool metrics

---

## Security Checklist

- [ ] JWT secret in Secret Manager (not env var)
- [ ] CORS whitelist (no wildcards)
- [ ] httpOnly cookies (no localStorage)
- [ ] Input validation (Pydantic)
- [ ] SQL parameterization (asyncpg)
- [ ] No PII in logs
- [ ] Rate limiting (10 req/sec per IP)
- [ ] Password hashing (bcrypt, cost=12)
- [ ] HTTPS only (Secure cookie flag)
- [ ] Content Security Policy headers

---

## Future Enhancements (Phase 2+)

- **Export**: CSV/Excel download for reports
- **Alerts**: Email/Slack when budget threshold hit
- **User Management**: Invite new admins, role management
- **Audit Log**: Track who viewed what and when
- **Real-time**: WebSocket for live KPI updates
- **Mobile**: Responsive design (already planned in Phase 1)
- **Dark Mode**: Theme toggle (Tailwind dark: classes)
- **Multi-org**: Switch between organizations (if needed)

---

## Open Questions

1. **User Table**: Do we need a new `admin_users` table, or use existing `users`/`members`?
   - **Decision**: Use existing `users` table, add `role` column if missing.

2. **Budget Limits**: Where to store monthly budget? New `organization_settings` table?
   - **Decision**: Hardcode $200/month for Phase 1. Config table in Phase 2.

3. **Time Zone**: Display times in JST or UTC?
   - **Decision**: Store UTC, display JST (browser-aware with date-fns).

4. **Member PII**: Can we show member names, or only IDs?
   - **Decision**: Names OK (internal tool). No raw messages.

---

## References

- [FastAPI Security Docs](https://fastapi.tiangolo.com/tutorial/security/)
- [TanStack Query Guide](https://tanstack.com/query/latest/docs/react/overview)
- [shadcn/ui Components](https://ui.shadcn.com/)
- [Vercel Deployment](https://vercel.com/docs)
- [Cloud Run Auth](https://cloud.google.com/run/docs/authenticating/public)

---

**Document Version**: 1.0
**Last Updated**: 2026-02-15
**Author**: Claude (Sonnet 4.5) + Kazu
