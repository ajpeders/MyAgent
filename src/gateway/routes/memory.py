"""Memory routes — /api/memory/*."""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from src.gateway.middleware import jwt_required
from src.services.memory.service import remember, recall, list_memories, forget


router = APIRouter()


class MemoryAddRequest(BaseModel):
    content: str


class MemoryResponse(BaseModel):
    memory_id: str
    content: str
    score: float | None = None
    created_at: float | None = None


@router.post("/api/memory", response_model=MemoryResponse)
def memory_add(request: Request, body: MemoryAddRequest):
    payload = jwt_required(request)
    user_id = payload["user_id"]
    memory_id = remember(body.content, user_id)
    return MemoryResponse(memory_id=memory_id, content=body.content)


@router.get("/api/memory", response_model=list[MemoryResponse])
def memory_list(request: Request, q: str = "", top_k: int = 5):
    payload = jwt_required(request)
    user_id = payload["user_id"]
    top_k = min(top_k, 100)
    if q:
        results = recall(q, user_id, top_k=top_k)
        return [
            MemoryResponse(memory_id=r["memory_id"], content=r["content"], score=r["score"], created_at=r["created_at"])
            for r in results
        ]
    else:
        results = list_memories(user_id)
        return [
            MemoryResponse(memory_id=r["memory_id"], content=r["content"], score=None, created_at=r["created_at"])
            for r in results
        ]


@router.delete("/api/memory/{memory_id}")
def memory_delete(request: Request, memory_id: str):
    payload = jwt_required(request)
    user_id = payload["user_id"]
    deleted = forget(memory_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True}