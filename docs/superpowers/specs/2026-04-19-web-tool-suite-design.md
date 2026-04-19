# Web Tool Suite — Design Spec

## Overview

A browser-based tool suite for MyAgent, served by the existing FastAPI backend. Each tool is a self-contained module with its own route and UI. The first tool (email client) will be designed separately.

## Decisions

| Decision         | Choice                                      |
| ---------------- | ------------------------------------------- |
| Framework        | React + TypeScript                          |
| Build tool       | Vite                                        |
| Styling          | terminal.css (classless) + custom CSS       |
| Location         | `web/` directory in the project root        |
| Serving          | FastAPI serves built files; Vite proxy in dev |
| Routing          | React Router — one route per tool           |
| Layout           | Sidebar nav + content area                  |
| First tool       | Mail (designed separately)                  |

## Project Structure

```
web/
├── index.html
├── vite.config.ts
├── tsconfig.json
├── package.json
├── src/
│   ├── main.tsx              # React entry point
│   ├── App.tsx               # Router setup, global layout
│   ├── api/                  # Shared API client
│   │   └── client.ts         # Base fetch wrapper (auth, error handling)
│   ├── components/           # Shared UI components
│   │   ├── Layout.tsx        # Shell: sidebar nav + content area
│   │   └── ...
│   ├── styles/
│   │   └── app.css           # Custom layout CSS (supplements terminal.css)
│   └── tools/
│       └── mail/
│           ├── MailPage.tsx   # Route component (placeholder initially)
│           └── ...            # Designed separately
```

### Adding a new tool

1. Create `tools/<tool-name>/` with a page component
2. Add a route in `App.tsx`
3. Add a nav entry in `Layout.tsx`

## Shell

The shell is the shared frame that every tool lives inside:

- **Sidebar:** Lists available tools, highlights the active one. Collapsible.
- **Content area:** Renders the matched route component.
- **Home page (`/`):** Simple landing with a list of available tools.
- The shell has no knowledge of individual tool internals.

## API Client

Shared fetch wrapper in `api/client.ts`:

- Prepends base URL (configurable for dev proxy vs production)
- Attaches `X-API-Key` header when configured
- Handles error responses consistently
- Each tool adds its own API module (e.g., `api/mail.ts`) that uses the shared client

## Dev & Build

### Development

- `npm run dev` starts Vite dev server (default: `localhost:5173`)
- Vite proxies `/api/*` to FastAPI (`localhost:8000`)
- Hot module reload for frontend changes

### Production

- `npm run build` outputs to `web/dist/`
- FastAPI serves `web/dist/` as static files
- SPA fallback: any non-`/api` route serves `index.html`

## FastAPI Integration

Changes to `server.py`:

- Mount `web/dist/` for static file serving (replaces current `static/` mount)
- Add catch-all route for SPA fallback (serves `index.html` for non-API paths)
- All new API endpoints live under `/api/` prefix
- Existing `/chat` and `/health` endpoints remain unchanged

## Styling

- **terminal.css** provides the base aesthetic — monospace, terminal theme, classless semantic styling
- **Custom CSS** (`styles/app.css`) handles layout concerns: sidebar, grid, responsive behavior
- No utility CSS framework (no Tailwind) — keep it simple, lean into terminal.css defaults

## Scope of Initial Build

1. Scaffold Vite + React + TS in `web/`
2. Install and configure terminal.css
3. Build the shell (Layout with sidebar, router, home page)
4. Shared API client with auth support
5. FastAPI integration (static serving + SPA fallback)
6. Placeholder mail tool route (empty page)
