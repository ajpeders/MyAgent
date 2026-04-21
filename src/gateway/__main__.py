"""Gateway server — FastAPI entry point. Orchestrates services."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import ALLOWED_ORIGINS
from gateway.routes import auth, memory, search, mail, chat


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(memory.router)
app.include_router(search.router)
app.include_router(mail.router)
app.include_router(chat.router)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)