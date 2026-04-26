from __future__ import annotations
from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.generate import router as generate_router
from app.api.v1.batch import router as batch_router
from app.api.v1.templates import router as templates_router
from app.api.v1.admin import router as admin_router
from app.api.v1.admin_llm import router as admin_llm_router
from app.api.v1.contributions import router as contributions_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.intent_builder import router as intent_builder_router

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(auth_router)
v1_router.include_router(generate_router)
v1_router.include_router(batch_router)
v1_router.include_router(templates_router)
v1_router.include_router(admin_router)
v1_router.include_router(admin_llm_router)
v1_router.include_router(contributions_router)
v1_router.include_router(notifications_router)
v1_router.include_router(intent_builder_router)
