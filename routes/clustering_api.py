from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database import get_db
from utils.standard_response import standard_response
from algorithms.clustering import sweep_algorithm, nearest_neighbor_route
from models import Cluster, ClusterRoute, DailyPengepul, Vehicle
from datetime import date

router = APIRouter()

@router.get("/clustering-hybrid")
def clustering_hybrid(tanggal: date = Query(...), db: Session = Depends(get_db)):
    locations = db.query(DailyPengepul).filter(
        DailyPengepul.tanggal_cluster == tanggal
    ).order_by(DailyPengepul.sudut_polar).all()
    
    vehicles = db.query(Vehicle).order_by(Vehicle.kapasitas_kendaraan.desc()).all()

    if not locations or not vehicles:
        return standard_response(message="Data lokasi atau kendaraan kosong")

    last_cluster = db.query(Cluster).order_by(Cluster.cluster_id.desc()).first()
    start_cluster_id = (last_cluster.cluster_id + 1) if last_cluster else 1

    # SWEEP
    clusters = sweep_algorithm(locations, vehicles, start_cluster_id=start_cluster_id)

    save_clusters(db, clusters)

    # NEAREST NEIGHBOR
    routes = []
    for cluster in clusters:
        optimized_route = nearest_neighbor_route(
            cluster["locations"], 
            cluster_id=cluster["cluster_id"], 
            vehicle_id=cluster["vehicle_id"]
        )
        routes.append({
            "cluster_id": cluster["cluster_id"],
            "vehicle_id": cluster["vehicle_id"],
            "locations": optimized_route
        })

    save_routes(db, routes)

    return standard_response(data={"total_cluster": len(clusters), "clusters": routes})

# ----------------------------------------
# SAVE CLUSTERS & ROUTES FUNCTION (REVISED)
# ----------------------------------------

# SAVE CLUSTERS FUNCTION (REVISED)
def save_clusters(db: Session, clusters: list[dict]):
    for cluster in clusters:
        if not cluster["locations"]:
            continue
        new_cluster = Cluster(
            cluster_id=cluster["cluster_id"],
            daily_pengepul_id=cluster["locations"][0]["id"],  # <-- ambil dari locations
            vehicle_id=cluster["vehicle_id"]
        )
        db.add(new_cluster)
    db.commit()

def save_routes(db: Session, routes: list[dict]):
    for route in routes:
        for loc in route["locations"]:
            new_route = ClusterRoute(
                cluster_id=route["cluster_id"],
                vehicle_id=route["vehicle_id"],
                order_no=loc["order_no"],
                daily_pengepul_id=loc["daily_pengepul_id"],  # <--- fix disini
                nama_pengepul=loc["nama_pengepul"],
                alamat=loc["alamat"],
                waktu_tempuh=loc["waktu_tempuh"],
                jarak_tempuh_km=loc["jarak_tempuh_km"]
            )
            db.add(new_route)
    db.commit()
