# Web Tool Suite Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a React + TypeScript tool suite shell served by FastAPI, styled with terminal.css, with a placeholder mail tool route.

**Architecture:** Vite-scaffolded React app in `web/`, served as static files by FastAPI in production, with Vite dev proxy in development. Sidebar + content layout with React Router. Each tool is a route with its own directory under `tools/`.

**Tech Stack:** React 19, TypeScript, Vite, React Router, terminal.css, FastAPI

**Spec:** `docs/superpowers/specs/2026-04-19-web-tool-suite-design.md`

---

## Chunk 1: Scaffold and Shell

### Task 1: Scaffold Vite + React + TypeScript

**Files:**
- Create: `web/` (entire scaffolded directory)
- Modify: `.gitignore`

- [ ] **Step 1: Scaffold the Vite project**

```bash
cd /home/alex/projects/MyAgent
npm create vite@latest web -- --template react-ts
```

- [ ] **Step 2: Install dependencies**

```bash
cd /home/alex/projects/MyAgent/web
npm install
npm install react-router-dom
npm install terminal.css
```

- [ ] **Step 3: Add `web/dist/` and `web/node_modules/` to `.gitignore`**

Append to `/home/alex/projects/MyAgent/.gitignore`:

```
# Web frontend
web/dist/
web/node_modules/
```

- [ ] **Step 4: Verify scaffold works**

```bash
cd /home/alex/projects/MyAgent/web
npm run dev -- --port 5173
```

Expected: Vite dev server starts, default React page loads at `localhost:5173`.

- [ ] **Step 5: Commit**

```bash
git add web/ .gitignore
git commit -m "scaffold: Vite + React + TypeScript in web/"
```

---

### Task 2: Configure Vite proxy and terminal.css

**Files:**
- Modify: `web/vite.config.ts`
- Modify: `web/src/main.tsx`
- Delete: `web/src/App.css`, `web/src/index.css` (Vite defaults, replaced by terminal.css)

- [ ] **Step 1: Configure Vite proxy**

Replace `web/vite.config.ts`:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
```

- [ ] **Step 2: Import terminal.css and clean up defaults**

Delete `web/src/App.css` and `web/src/index.css`.

Replace `web/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "terminal.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
```

- [ ] **Step 3: Verify terminal.css applies**

Replace `web/src/App.tsx` temporarily:

```tsx
export default function App() {
  return (
    <div className="container">
      <h1>MyAgent</h1>
      <p>terminal.css is working.</p>
    </div>
  );
}
```

Run `npm run dev` and confirm monospace terminal styling appears.

- [ ] **Step 4: Commit**

```bash
git add web/
git commit -m "configure Vite proxy and terminal.css"
```

---

### Task 3: Build the tool registry and Layout shell

**Files:**
- Create: `web/src/tools/registry.ts`
- Create: `web/src/components/Layout.tsx`
- Create: `web/src/styles/app.css`
- Create: `web/src/tools/mail/MailPage.tsx`

- [ ] **Step 1: Create the tool registry**

This is the single source of truth for all tools — both sidebar and home page read from it.

Create `web/src/tools/registry.ts`:

```ts
export interface ToolEntry {
  name: string;
  path: string;
  description: string;
}

export const tools: ToolEntry[] = [
  {
    name: "Mail",
    path: "/mail",
    description: "Read and triage email across accounts",
  },
];
```

- [ ] **Step 2: Create the mail placeholder**

Create `web/src/tools/mail/MailPage.tsx`:

```tsx
export default function MailPage() {
  return (
    <>
      <h1>Mail</h1>
      <p>Email tool — coming soon.</p>
    </>
  );
}
```

- [ ] **Step 3: Create layout CSS**

Create `web/src/styles/app.css`:

```css
/* Shell layout — supplements terminal.css */

.shell {
  display: flex;
  height: 100vh;
}

.sidebar {
  width: 200px;
  border-right: 2px solid var(--secondary-color, #ccc);
  padding: 1rem;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
}

.sidebar h2 {
  font-size: 1rem;
  margin-bottom: 1rem;
}

.sidebar nav ul {
  list-style: none;
  padding: 0;
}

.sidebar nav li {
  margin-bottom: 0.5rem;
}

.sidebar nav a {
  text-decoration: none;
}

.sidebar nav a.active {
  font-weight: bold;
  text-decoration: underline;
}

.sidebar .collapse-btn {
  margin-top: auto;
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
  padding: 0.25rem 0;
  font-family: inherit;
  font-size: inherit;
  color: inherit;
}

.sidebar.collapsed {
  width: 40px;
  padding: 0.5rem;
  overflow: hidden;
}

.sidebar.collapsed h2,
.sidebar.collapsed nav,
.sidebar.collapsed .collapse-btn span {
  display: none;
}

.content {
  flex: 1;
  padding: 2rem;
  overflow-y: auto;
}
```

- [ ] **Step 4: Create the Layout component**

Create `web/src/components/Layout.tsx`:

```tsx
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { tools } from "../tools/registry";
import "../styles/app.css";

export default function Layout() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="shell">
      <aside className={`sidebar${collapsed ? " collapsed" : ""}`}>
        <h2>MyAgent</h2>
        <nav>
          <ul>
            <li>
              <NavLink to="/" end>
                Home
              </NavLink>
            </li>
            {tools.map((tool) => (
              <li key={tool.path}>
                <NavLink to={tool.path}>{tool.name}</NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <button
          className="collapse-btn"
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? ">" : "<"} <span>collapse</span>
        </button>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 5: Commit**

```bash
git add web/src/
git commit -m "add tool registry, Layout shell, and mail placeholder"
```

---

### Task 4: Wire up React Router and Home page

**Files:**
- Modify: `web/src/App.tsx`
- Create: `web/src/tools/HomePage.tsx`

- [ ] **Step 1: Create the Home page**

Create `web/src/tools/HomePage.tsx`:

```tsx
import { Link } from "react-router-dom";
import { tools } from "./registry";

export default function HomePage() {
  return (
    <>
      <h1>MyAgent Tools</h1>
      <ul>
        {tools.map((tool) => (
          <li key={tool.path}>
            <Link to={tool.path}>
              <strong>{tool.name}</strong>
            </Link>{" "}
            — {tool.description}
          </li>
        ))}
      </ul>
    </>
  );
}
```

- [ ] **Step 2: Set up routing in App.tsx**

Replace `web/src/App.tsx`:

```tsx
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import HomePage from "./tools/HomePage";
import MailPage from "./tools/mail/MailPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="mail" element={<MailPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
```

- [ ] **Step 3: Verify routing works**

Run `npm run dev`. Confirm:
- `/` shows the home page with the tool list
- `/mail` shows the mail placeholder
- Sidebar highlights the active route
- Collapse button toggles the sidebar

- [ ] **Step 4: Commit**

```bash
git add web/src/
git commit -m "wire up React Router with home page and mail route"
```

---

### Task 5: Create shared API client

**Files:**
- Create: `web/src/api/client.ts`

- [ ] **Step 1: Create the API client**

Create `web/src/api/client.ts`:

```ts
const API_KEY = import.meta.env.VITE_API_KEY ?? "";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (API_KEY) {
    headers.set("X-API-Key", API_KEY);
  }

  const res = await fetch(path, { ...options, headers });

  if (!res.ok) {
    const body = await res.text();
    throw new ApiError(res.status, body);
  }

  return res.json();
}
```

- [ ] **Step 2: Commit**

```bash
git add web/src/api/
git commit -m "add shared API client with auth support"
```

---

## Chunk 2: FastAPI Integration

### Task 6: Update server.py for SPA serving

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Update server.py**

Replace `server.py` with these changes:
- Move `/chat` to `/api/chat`
- Remove old `GET /` route and `static/` mount
- Add static file mount for `web/dist/`
- Add SPA fallback catch-all
- Update auth middleware to only check `/api` paths

```python
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import DEFAULT_MODEL, API_KEY, ALLOWED_ORIGINS
from executor import dispatch_session
from session_store import SessionState, load_session, save_session

app = FastAPI()
WEB_DIST = Path(__file__).parent / "web" / "dist"

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if API_KEY and request.url.path.startswith("/api"):
        key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if key != API_KEY:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return await call_next(request)


# --- API models ---

class ChatRequest(BaseModel):
    prompt: str
    model: str = DEFAULT_MODEL
    session_id: str | None = None
    confirm: bool = False


class ActionResponse(BaseModel):
    type: str
    content: str
    agent: str | None = None
    pending_confirm: str | None = None


# --- API routes ---

@app.post("/api/chat", response_model=list[ActionResponse])
def chat(req: ChatRequest):
    if req.session_id:
        state = load_session(req.session_id, req.model)
        results = dispatch_session(state, req.prompt, interactive=False, confirm=req.confirm)
        save_session(state)
    else:
        state = SessionState(session_id="_stateless", model=req.model)
        results = dispatch_session(state, req.prompt)

    return [
        ActionResponse(
            type=r["type"],
            content=r["content"],
            agent=r.get("agent"),
            pending_confirm=r.get("pending_confirm"),
        )
        for r in results
    ]


@app.get("/health")
def health():
    return {"status": "ok"}


# --- SPA serving ---

if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        if path.startswith("api"):
            raise HTTPException(status_code=404, detail="Not found")
        file = WEB_DIST / path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(WEB_DIST / "index.html")
```

- [ ] **Step 2: Verify `/health` still works**

```bash
cd /home/alex/projects/MyAgent
uvicorn server:app --port 8000 &
curl http://localhost:8000/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "update server.py: move chat to /api/chat, add SPA serving"
```

---

### Task 7: Update start.sh to build frontend

**Files:**
- Modify: `start.sh`

- [ ] **Step 1: Add frontend build step to start.sh**

Replace `start.sh`:

```bash
#!/usr/bin/env bash
# Start mac-agent server with outside-accessible binding.
# Set MAC_AGENT_API_KEY before running in production.
#
# Usage:
#   ./start.sh                          # defaults: 0.0.0.0:8000, no auth
#   MAC_AGENT_API_KEY=secret ./start.sh # with API key protection
#   PORT=9000 ./start.sh                # custom port

set -euo pipefail

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

if [ -z "${MAC_AGENT_API_KEY:-}" ]; then
    echo "WARNING: MAC_AGENT_API_KEY is not set. Server is unprotected." >&2
fi

# Build frontend
if [ -d "web" ] && [ -f "web/package.json" ]; then
    echo "Building frontend..." >&2
    (cd web && npm install --silent && npm run build)
fi

exec uvicorn server:app --host "$HOST" --port "$PORT"
```

- [ ] **Step 2: Verify the full flow**

```bash
cd /home/alex/projects/MyAgent
./start.sh &
curl http://localhost:8000/
```

Expected: Returns the React app's `index.html`.

- [ ] **Step 3: Commit**

```bash
git add start.sh
git commit -m "update start.sh to build frontend before starting server"
```

---

### Task 8: Clean up old static frontend

**Files:**
- Modify: `web/index.html` (Vite's entry — update title)
- Note: `static/index.html` remains for now (not deleted until new UI is confirmed working)

- [ ] **Step 1: Update Vite's index.html title**

In `web/index.html`, change the `<title>` to `MyAgent`.

- [ ] **Step 2: Remove Vite boilerplate assets**

```bash
rm -f web/src/assets/react.svg web/public/vite.svg
```

- [ ] **Step 3: Verify everything end-to-end**

```bash
cd /home/alex/projects/MyAgent/web
npm run build
cd ..
uvicorn server:app --port 8000
```

Then open `http://localhost:8000` in a browser. Confirm:
- Home page renders with tool list
- `/mail` route works
- Sidebar navigation works
- terminal.css styling applies
- `/health` returns JSON
- `/api/chat` accepts POST requests

- [ ] **Step 4: Commit**

```bash
git add web/ 
git commit -m "clean up Vite boilerplate, finalize initial web shell"
```

---

## Chunk 3: Update project documentation

### Task 9: Update CLAUDE.md and project config

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add web frontend section to CLAUDE.md**

Add after the "Running" section:

```markdown
## Web Frontend

React + TypeScript app in `web/`, styled with terminal.css. Each tool is a route under `tools/`.

### Development
```bash
cd web && npm run dev    # Vite dev server on :5173, proxies /api to :8000
```

### Adding a new tool
1. Create `web/src/tools/<name>/` with a page component
2. Add entry to `web/src/tools/registry.ts`
3. Add route in `web/src/App.tsx`
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "document web frontend in CLAUDE.md"
```
