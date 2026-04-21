"""Memory routes — /api/memory/*."""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from gateway.middleware import get_user_id
from services.memory.service import remember, recall, list_memories, forget


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
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    memory_id = remember(body.content, user_id)
    return MemoryResponse(memory_id=memory_id, content=body.content)


@router.get("/api/memory", response_model=list[MemoryResponse])
def memory_list(request: Request, q: str = "", top_k: int = 5):
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
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
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    deleted = forget(memory_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True}