from fastapi import APIRouter

from app.routers import historical, laps, mileage, reference, setup, testing, tracks, tyres
from app.schemas.common import error_responses

api_router = APIRouter(responses=error_responses(422))
api_router.include_router(reference.router)
api_router.include_router(tracks.router)
api_router.include_router(testing.router)
api_router.include_router(setup.router)
api_router.include_router(laps.router)
api_router.include_router(mileage.router)
api_router.include_router(historical.router)
api_router.include_router(tyres.router)
