from fastapi import FastAPI, Request, APIRouter
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware  # 🆕 CORS middleware

from auth import auth_router, token_blacklist
from location import location_router
from vehicle import vehicle_router
from clustering import cluster_router
from distance import distance_router
from daily_pengepul import router as daily_pengepul_router
from database import Base, engine

import os

import jwt

SECRET_KEY = "rahasia123"
ALGORITHM = "HS256"

app = FastAPI(title="Logistics API")

# 🆕 Tambahin CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4202"],  # alamat Angular lo
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DB setup
Base.metadata.create_all(bind=engine)

# Middleware cek token
@app.middleware("http")
async def check_token_middleware(request: Request, call_next):
    allowed_paths = [
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/docs",
        "/openapi.json",
        "/",
        "/favicon.ico",
        "/redoc"
    ]
    
    if not any(request.url.path.startswith(path) for path in allowed_paths):
        token = request.headers.get("Authorization")
        if token:
            token = token.replace("Bearer ", "")
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                if token in token_blacklist:
                    return JSONResponse(status_code=401, content={"data": None, "message": "Token sudah logout"})
            except jwt.ExpiredSignatureError:
                return JSONResponse(status_code=401, content={"data": None, "message": "Token kedaluwarsa"})
            except jwt.InvalidTokenError:
                return JSONResponse(status_code=401, content={"data": None, "message": "Token tidak valid"})
        else:
            return JSONResponse(status_code=401, content={"data": None, "message": "Token tidak ditemukan"})
    return await call_next(request)

# Redirect root
@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")

# Optional response helper
def standard_response(data=None, message="Success", status_code=200):
    return JSONResponse(status_code=status_code, content={"data": data, "message": message})

# Routing
api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_v1_router.include_router(location_router, prefix="/locations", tags=["Locations"])
api_v1_router.include_router(vehicle_router, prefix="/vehicles", tags=["Vehicles"])
api_v1_router.include_router(cluster_router, prefix="/clusters", tags=["Clustering"])
api_v1_router.include_router(distance_router, prefix="/distance_matrix", tags=["Distance Matrix"])
api_v1_router.include_router(daily_pengepul_router, prefix="/pengepul", tags=["Daily Pengepul"])

app.include_router(api_v1_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=False
    )