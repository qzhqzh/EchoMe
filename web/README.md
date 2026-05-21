# EchoMe Web Console

A modern dark-themed memory management dashboard for EchoMe Hub.

## Tech Stack

- **Vue 3** + TypeScript
- **Vite** (dev server + bundler)
- **Tailwind CSS** (utility-first styling)
- **Vue Router** (client-side routing)

## Getting Started

### Prerequisites

- Node.js 18+
- EchoMe Hub running on port 20000 (or configure via login page)

### Install dependencies

```bash
cd web
npm install
```

### Development

```bash
npm run dev
```

The dev server starts on `http://localhost:3000` and proxies `/api` requests to `http://localhost:20000`.

### Production Build

```bash
npm run build
```

Output is in `dist/`. Serve statically with any web server.

## Configuration

On the login page, you can configure:

- **API Token**: Your Bearer token (set in Hub's `.env`)
- **Hub URL**: If Hub is not on the same origin (e.g., `http://localhost:20000`)

Both are stored in `localStorage`.

## Features

- **Dashboard**: Overview with memory counts, type distribution, and quick search
- **Memories**: Full CRUD with filters (type, layer, status, tags), search, pagination
- **Memory Detail**: View/edit/delete with full metadata display
- **Review Queue**: Approve or reject AI-suggested memories
- **Projects**: Manage project scopes for memory targeting

## Architecture

```
src/
├── api/client.ts      # Typed API client with auth handling
├── stores/
│   ├── auth.ts        # Token + API base management
│   └── toast.ts       # Toast notification state
├── components/        # Reusable UI components
├── views/             # Page-level components
├── types.ts           # TypeScript interfaces + color maps
├── router.ts          # Vue Router config with auth guard
└── styles/main.css    # Tailwind + custom component classes
```

## Design

- Dark theme (slate palette) by default
- Color-coded memory types, layers, and statuses
- Responsive with mobile sidebar
- Toast notifications for all actions
- Skeleton loading states
