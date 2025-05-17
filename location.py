from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from database import get_db
from models import Location
from schemas import LocationCreate, LocationResponse
from auth import get_current_user
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

location_router = APIRouter()

def standard_response(data=None, message="Success", status_code=200, error=None):
    return JSONResponse(
        status_code=status_code,
        content={
            "message": message,
            "data": jsonable_encoder(data),
            "error": error
        }
    )

# ✅ Helper buat nambah field status_diambil ke response
def add_status_diambil(location: Location):
    response_data = LocationResponse.from_orm(location).dict()
    response_data["status_diambil"] = "sudah diambil" if location.sudah_diambil else "belum diambil"
    return response_data

@location_router.post("/")
def create_location(
    location: LocationCreate = Depends(LocationCreate.as_form),
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    try:
        sudut_polar = Location.calculate_polar_angle(location.latitude, location.longitude)
        new_location = Location(
            nama_pengepul=location.nama_pengepul,
            alamat=location.alamat,
            latitude=location.latitude,
            longitude=location.longitude,
            nilai_ekspektasi=location.nilai_ekspektasi,
            sudut_polar=sudut_polar,
            sudah_diambil=False  # default value
        )
        db.add(new_location)
        db.commit()
        db.refresh(new_location)

        return standard_response(
            data=add_status_diambil(new_location),
            message="Lokasi berhasil ditambahkan"
        )
    except Exception as e:
        return standard_response(
            data=None,
            message="Terjadi kesalahan pada server",
            status_code=500,
            error=str(e)
        )

@location_router.get("/")
def get_locations(db: Session = Depends(get_db), user=Depends(get_current_user)):
    try:
        locations = db.query(Location).all()
        return standard_response(
            data=[add_status_diambil(loc) for loc in locations],
            message="Berhasil mengambil semua lokasi"
        )
    except Exception as e:
        return standard_response(
            data=None,
            message="Terjadi kesalahan saat mengambil lokasi",
            status_code=500,
            error=str(e)
        )

@location_router.get("/{location_id}")
def get_location(location_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    try:
        location = db.query(Location).filter(Location.id == location_id).first()
        if not location:
            raise HTTPException(status_code=404, detail="Lokasi tidak ditemukan")
        return standard_response(
            data=add_status_diambil(location),
            message="Berhasil mengambil detail lokasi"
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        return standard_response(
            data=None,
            message="Terjadi kesalahan saat mengambil detail lokasi",
            status_code=500,
            error=str(e)
        )

@location_router.put("/{location_id}")
def update_location(
    location_id: int,
    updated_location: LocationCreate = Depends(LocationCreate.as_form),
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    try:
        location = db.query(Location).filter(Location.id == location_id).first()
        if not location:
            raise HTTPException(status_code=404, detail="Lokasi tidak ditemukan")

        sudut_polar = Location.calculate_polar_angle(updated_location.latitude, updated_location.longitude)

        location.nama_pengepul = updated_location.nama_pengepul
        location.alamat = updated_location.alamat
        location.latitude = updated_location.latitude
        location.longitude = updated_location.longitude
        location.nilai_ekspektasi = updated_location.nilai_ekspektasi
        location.sudut_polar = sudut_polar

        db.commit()
        db.refresh(location)

        return standard_response(
            data=add_status_diambil(location),
            message="Lokasi berhasil diperbarui"
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        return standard_response(
            data=None,
            message="Terjadi kesalahan saat memperbarui lokasi",
            status_code=500,
            error=str(e)
        )

@location_router.delete("/{location_id}")
def delete_location(location_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    try:
        location = db.query(Location).filter(Location.id == location_id).first()
        if not location:
            raise HTTPException(status_code=404, detail="Lokasi tidak ditemukan")

        db.delete(location)
        db.commit()

        return standard_response(data=None, message="Lokasi berhasil dihapus")
    except HTTPException as e:
        raise e
    except Exception as e:
        return standard_response(
            data=None,
            message="Terjadi kesalahan saat menghapus lokasi",
            status_code=500,
            error=str(e)
        )
