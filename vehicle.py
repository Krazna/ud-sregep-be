from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy.orm import Session
from database import get_db
from models import Cluster, ClusterRoute, Vehicle
from schemas import VehicleCreate, VehicleResponse
from auth import get_current_user
from fastapi.responses import JSONResponse
from typing import List

vehicle_router = APIRouter()

def standard_response(data=None, message="Success", status_code=200):
    return JSONResponse(
        status_code=status_code,
        content={
            "message": message,
            "data": data
        }
    )

# Ambil semua kendaraan
@vehicle_router.get("/")
def get_vehicles(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    vehicles = db.query(Vehicle).all()
    response_data = [VehicleResponse.from_orm(v).model_dump() for v in vehicles]
    return standard_response(data=response_data, message="Berhasil mengambil semua kendaraan")

@vehicle_router.get("/{vehicle_id}")
def get_vehicle_by_id(
    vehicle_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if db_vehicle is None:
        raise HTTPException(status_code=404, detail="Kendaraan tidak ditemukan")

    return standard_response(
        data=VehicleResponse.from_orm(db_vehicle).model_dump(),
        message="Berhasil mengambil detail kendaraan"
    )
    
# Tambah kendaraan baru
@vehicle_router.post("/")
def create_vehicle(
    vehicle: VehicleCreate = Depends(VehicleCreate.as_form),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    new_vehicle = Vehicle(
        nama_kendaraan=vehicle.nama_kendaraan,
        kapasitas_kendaraan=vehicle.kapasitas_kendaraan
    )
    db.add(new_vehicle)
    db.commit()
    db.refresh(new_vehicle)
    return standard_response(
        data=VehicleResponse.from_orm(new_vehicle).model_dump(),
        message="Kendaraan berhasil ditambahkan"
    )

# Ambil kendaraan berdasarkan ID
@vehicle_router.delete("/{vehicle_id}")
def delete_vehicle(
    vehicle_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if db_vehicle is None:
        raise HTTPException(status_code=404, detail="Kendaraan tidak ditemukan")

    # 🔍 Cek relasi dengan clusters dan cluster_routes
    used_in_clusters = db.query(Cluster).filter(Cluster.vehicle_id == vehicle_id).count()
    used_in_routes = db.query(ClusterRoute).filter(ClusterRoute.vehicle_id == vehicle_id).count()

    if used_in_clusters > 0 or used_in_routes > 0:
        return standard_response(
            data=None,
            message=f"Kendaraan tidak bisa dihapus karena masih digunakan dalam {used_in_clusters} cluster dan {used_in_routes} route.",
            status_code=400
        )

    db.delete(db_vehicle)
    db.commit()
    return standard_response(data=None, message="Kendaraan berhasil dihapus")

# Perbarui data kendaraan
@vehicle_router.put("/{vehicle_id}")
def update_vehicle(
    vehicle_id: int,
    vehicle: VehicleCreate = Depends(VehicleCreate.as_form),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if db_vehicle is None:
        raise HTTPException(status_code=404, detail="Kendaraan tidak ditemukan")
    
    db_vehicle.nama_kendaraan = vehicle.nama_kendaraan
    db_vehicle.kapasitas_kendaraan = vehicle.kapasitas_kendaraan
    db.commit()
    db.refresh(db_vehicle)
    return standard_response(
        data=VehicleResponse.from_orm(db_vehicle).model_dump(),
        message="Kendaraan berhasil diperbarui"
    )

# Hapus kendaraan
@vehicle_router.delete("/{vehicle_id}")
def delete_vehicle(
    vehicle_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if db_vehicle is None:
        raise HTTPException(status_code=404, detail="Kendaraan tidak ditemukan")

    try:
        # Cari semua cluster yang pakai kendaraan ini
        clusters = db.query(Cluster).filter(Cluster.vehicle_id == vehicle_id).all()
        
        # Hapus cluster_route yang terkait kendaraan ini
        db.query(ClusterRoute).filter(ClusterRoute.vehicle_id == vehicle_id).delete(synchronize_session=False)
        
        # Hapus cluster yang terkait kendaraan ini
        for cluster in clusters:
            db.delete(cluster)
        
        # Baru hapus kendaraan
        db.delete(db_vehicle)
        db.commit()

        return standard_response(data=None, message="Kendaraan dan semua relasinya berhasil dihapus")
    except Exception as e:
        db.rollback()
        return standard_response(
            data=None,
            message="Terjadi kesalahan saat menghapus kendaraan",
            status_code=500,
            error=str(e)
        )

# --- SCHEMAS ---

from pydantic import BaseModel

class VehicleCreate(BaseModel):
    nama_kendaraan: str
    kapasitas_kendaraan: int

    @classmethod
    def as_form(
        cls,
        nama_kendaraan: str = Form(...),
        kapasitas_kendaraan: int = Form(...)
    ):
        return cls(
            nama_kendaraan=nama_kendaraan,
            kapasitas_kendaraan=kapasitas_kendaraan
        )

class VehicleResponse(BaseModel):
    id: int
    nama_kendaraan: str
    kapasitas_kendaraan: int

    class Config:
        from_attributes = True  # For Pydantic v2
