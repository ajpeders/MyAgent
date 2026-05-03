"""News service models."""
from pydantic import BaseModel


VALID_TOPICS = {"Tech", "Music", "World", "US News", "Hip Hop", "Gaming"}


class CreateSourceRequest(BaseModel):
    label: str
    topic: str  # Top | World | Business | Tech
    feed_url: str


class UpdateSourceRequest(BaseModel):
    enabled: bool


class RatingRequest(BaseModel):
    rating: int  # 1 or -1


class NewsSource(BaseModel):
    id: str
    user_id: str
    label: str
    topic: str
    feed_url: str
    enabled: bool
    created_at: float


class NewsArticle(BaseModel):
    id: str
    source_id: str
    source_label: str
    title: str
    topic: str
    url: str
    published_at: str
    summary: str | None = None
