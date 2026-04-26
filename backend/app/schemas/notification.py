from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: str
    type: str
    payload: dict
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationsListOut(BaseModel):
    total_unread: int
    notifications: list[NotificationOut]
