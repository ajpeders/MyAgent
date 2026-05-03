"""Profile routes — /api/profile/*."""
from fastapi import APIRouter, Request

from src.gateway.middleware import jwt_required
from src.services.profile.models import (
    LogSignalRequest,
    UpdateInterestsRequest,
    UpdateModelConfigRequest,
)
from src.services.profile.service import ProfileService

router = APIRouter()
_profile = ProfileService()


@router.get("/api/profile")
async def get_profile(request: Request):
    payload = jwt_required(request)
    user_id = payload["user_id"]
    return {
        "interests": _profile.get_interests(user_id),
        "model_config": _profile.get_model_config(user_id),
    }


@router.put("/api/profile/interests")
async def set_interests(request: Request, body: UpdateInterestsRequest):
    payload = jwt_required(request)
    _profile.set_interests(payload["user_id"], body.interests)
    return {"status": "ok"}


@router.put("/api/profile/models")
async def set_model_config(request: Request, body: UpdateModelConfigRequest):
    payload = jwt_required(request)
    _profile.set_model_config(payload["user_id"], body.config)
    return {"status": "ok"}


@router.post("/api/profile/signal")
async def log_signal(request: Request, body: LogSignalRequest):
    payload = jwt_required(request)
    _profile.log_signal(
        user_id=payload["user_id"],
        signal_type=body.signal_type,
        topic=body.topic,
        source=body.source,
    )
    return {"status": "ok"}
