from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import DEFAULT_MODEL, API_KEY, ALLOWED_ORIGINS
from executor import dispatch_session
from session_store import SessionState, load_session, save_session

app = FastAPI()
INDEX_HTML = Path(__file__).parent / "static" / "index.html"

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if API_KEY and request.url.path not in ("/", "/health"):
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


# --- Routes ---

@app.post("/chat", response_model=list[ActionResponse])
def chat(req: ChatRequest):
    if req.session_id:
        # Multi-turn: load, dispatch, persist
        state = load_session(req.session_id, req.model)
        results = dispatch_session(state, req.prompt, interactive=False, confirm=req.confirm)
        save_session(state)
    else:
        # Stateless: throwaway session, nothing persisted
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


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML.read_text().replace("__DEFAULT_MODEL__", DEFAULT_MODEL)


app.mount("/static", StaticFiles(directory="static"), name="static")
