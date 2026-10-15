from fastapi import APIRouter

from app.routers import reference, testing, tracks
from app.schemas.common import error_responses

api_router = APIRouter(responses=error_responses(422))
api_router.include_router(reference.router)
api_router.include_router(tracks.router)
api_router.include_router(testing.router)
