# EchoMe Web Console

The Vue console for EchoMe's personal memories and project context: authoring, review, project knowledge, diagnostics, and quality evaluation.

## Tech Stack

- **Vue 3** + TypeScript
- **Vite** (dev server + bundler)
- **Tailwind CSS** (utility-first styling)
- **Vue Router** (client-side routing)

## Getting Started

### Prerequisites

- Node.js 20+ (matches repository CI)
- EchoMe Hub running on port 20000 (or configure via login page)

### Install dependencies

```bash
cd web
npm ci
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

- **GitHub login**: The default authentication flow; configure OAuth on the Hub first.
- **Manual token login**: An optional entry for an existing EchoMe token. Current user login issues JWTs; a shared token in `.env` is a legacy compatibility path.
- **Hub URL**: An advanced setting for a different API origin; otherwise requests use the same origin and the development proxy.

The browser stores the token, user metadata, and optional API base in `localStorage`. See the [deployment guide](../docs/deployment.md) for Hub configuration.

## Features

- **Dashboard**: Overview with memory counts, type distribution, and quick search
- **Memories**: Full CRUD with filters (type, layer, status, tags), search, pagination
- **Memory Detail**: View/edit/delete with full metadata display
- **Review Queue**: Approve or reject AI-suggested memories
- **Projects**: Create/edit projects, configure Git remote and path patterns, and browse associated memories
- **Project Workspace**: Inspect artifacts, constraints, context, and project quality evaluation
- **Diagnostics**: Memory graph, retrieval debugging, Context Runs/Outcomes, and Memory Eval
- **Memory Sleep**: Review proposals and inspect derived/source relationships
- **Market and Admin**: Public memory sharing and role-gated user administration

## Architecture

```
src/
├── api/client.ts      # Typed API client with auth handling
├── stores/
│   ├── auth.ts        # Token, user metadata, and API base management
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
