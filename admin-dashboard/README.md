# Soul-kun Admin Dashboard

Admin dashboard for Soul-kun project monitoring and analytics.

## Tech Stack

- **React 18** + **TypeScript 5**
- **Vite 6** - Build tool
- **Tailwind CSS 4** - Styling with Vite plugin
- **shadcn/ui** - Component library
- **TanStack Router** - Type-safe routing
- **TanStack Query** - Data fetching and caching
- **Recharts** - Data visualization
- **Lucide React** - Icons

## Getting Started

### Prerequisites

- Node.js 18+
- npm

### Installation

```bash
npm install
```

### Development

```bash
# Start dev server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Lint code
npm run lint
```

### Environment Variables

Create a `.env` file (copy from `.env.example`):

```bash
VITE_API_URL=http://localhost:8080/api/v1
```

## Project Structure

```
src/
├── components/
│   ├── ui/              # shadcn/ui components
│   ├── layout/          # Layout components (Sidebar, AppLayout)
│   └── dashboard/       # Dashboard-specific components
├── pages/               # Page components (routes)
├── hooks/               # React hooks (useAuth, etc.)
├── lib/
│   ├── api.ts           # API client
│   └── utils.ts         # Utility functions
└── types/
    └── api.ts           # TypeScript types for API responses
```

## Features

### Phase 1 MVP (Current)

- ✅ Authentication (login/logout)
- ✅ Protected routes
- ✅ Dashboard with KPI cards
- ✅ Responsive layout with sidebar
- ✅ Type-safe API client
- 🚧 Brain Analytics page
- 🚧 Cost Tracking page
- 🚧 Members page

### Planned Features

- Charts and data visualization
- Real-time data updates
- Export functionality
- Budget alerts
- Dark mode support

## Design Document

See [DESIGN.md](./DESIGN.md) for:
- Architecture overview
- Security decisions
- API endpoint specifications
- Deployment plan

## Development Notes

- All API calls use httpOnly cookies for authentication
- TypeScript strict mode enabled
- ESLint configured for React best practices
- Tailwind CSS v4 with new @import syntax
- shadcn/ui components use New York style with Zinc color scheme
