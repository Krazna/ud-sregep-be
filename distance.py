# distance.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from models import DailyPengepul, TimeDistanceMatrix
from database import get_db
from utils.routing import ors_directions_request
import json
from datetime import date

distance_router = APIRouter(prefix="/distance_matrix", tags=["Distance Matrix"])

@distance_router.get("/generate", summary="Generate & save adjusted ORS matrix")
def generate_matrix(
    tanggal: date = Query(..., description="Tanggal cluster yang ingin digunakan"),
    db: Session = Depends(get_db)
):
    pengepul_today = db.query(DailyPengepul).filter(DailyPengepul.tanggal_cluster == tanggal).all()

    if not pengepul_today:
        raise HTTPException(status_code=404, detail="No DailyPengepul data found for this date")

    if any(p.latitude is None or p.longitude is None for p in pengepul_today):
        raise HTTPException(status_code=400, detail="Some DailyPengepul entries have no coordinates")

    daily_pengepul_ids = [p.id for p in pengepul_today]
    coords = [(p.longitude, p.latitude) for p in pengepul_today]

    try:
        durations, distances = ors_directions_request(coords)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error while fetching adjusted matrix data: {e}")

    matrix_entry = TimeDistanceMatrix(
        location_ids=json.dumps(daily_pengepul_ids),
        time_matrix=json.dumps(durations),
        distance_matrix=json.dumps(distances)
    )

    db.add(matrix_entry)
    db.commit()

    return {
        "message": f"Matrix saved successfully with adjusted values for {tanggal}",
        "data": {
            "daily_pengepul_ids": daily_pengepul_ids,
            "time_matrix": durations,
            "distance_matrix": distances
        }
    }
