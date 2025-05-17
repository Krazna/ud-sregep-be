from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from models import DailyPengepul, Location
from schemas import DailyPengepulCreate, DailyPengepulResponse
from database import get_db
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from datetime import date
from sqlalchemy import text

router = APIRouter()

@router.post("/daily-pengepul")
def create_daily_pengepul(data: DailyPengepulCreate, db: Session = Depends(get_db)):
    created_entries = []

    for item in data.pengepul_list:
        # Cek duplikat
        existing = db.query(DailyPengepul).filter(
            DailyPengepul.tanggal_cluster == data.tanggal_cluster,
            DailyPengepul.location_id == item.location_id
        ).first()

        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Data pengepul dengan location_id {item.location_id} pada tanggal {data.tanggal_cluster} sudah ada."
            )

        # Ambil data dari tabel Location
        location = db.query(Location).filter(Location.id == item.location_id).first()
        if not location:
            raise HTTPException(status_code=404, detail=f"Location dengan id {item.location_id} tidak ditemukan.")

        # Simpan semua data ke DailyPengepul
        sudut = Location.get_sudut_polar_from_latlon(location.latitude, location.longitude)

        pengepul = DailyPengepul(
            tanggal_cluster=data.tanggal_cluster,
            location_id=item.location_id,
            nama_pengepul=location.nama_pengepul,
            alamat=location.alamat,
            nilai_ekspektasi=location.nilai_ekspektasi,
            nilai_ekspektasi_awal=location.nilai_ekspektasi,   # ✅ nilai awal disalin
            nilai_ekspektasi_akhir=location.nilai_ekspektasi,  # ✅ bisa berkurang pas proses cluster
            latitude=location.latitude,
            longitude=location.longitude,
            sudut_polar=sudut 
        )

        db.add(pengepul)
        created_entries.append(pengepul)

    db.commit()
    for entry in created_entries:
        db.refresh(entry)

    return JSONResponse(content=jsonable_encoder({
        "message": "Berhasil menyimpan data pengepul",
        "data": [DailyPengepulResponse.from_orm(entry) for entry in created_entries]
    }))

@router.get("/daily-pengepul")
def get_daily_pengepul(tanggal: date = Query(...), db: Session = Depends(get_db)):
    data = db.query(DailyPengepul).filter(DailyPengepul.tanggal_cluster == tanggal).all()
    
    return JSONResponse(content=jsonable_encoder({
        "message": "Berhasil mengambil data pengepul",
        "data": [DailyPengepulResponse.from_orm(item) for item in data]
    }))

@router.delete("/daily-pengepul/by-date")
def delete_daily_pengepul_by_date(
    tanggal: date = Query(...),
    db: Session = Depends(get_db)
):
    entries = db.query(DailyPengepul).filter(
        DailyPengepul.tanggal_cluster == tanggal
    ).all()

    if not entries:
        raise HTTPException(status_code=404, detail="Tidak ada data pengepul pada tanggal tersebut.")

    # Hapus dulu relasi anak di tabel clusters
    for entry in entries:
        db.execute(
            text("DELETE FROM clusters WHERE daily_pengepul_id = :id"),
            {"id": entry.id}
        )
    db.commit()

    # Baru hapus parent
    for entry in entries:
        db.delete(entry)
    db.commit()

    return JSONResponse(content={"message": f"{len(entries)} data pengepul berhasil dihapus"})

@router.delete("/daily-pengepul/{id}")
def delete_daily_pengepul_by_id(id: int, db: Session = Depends(get_db)):
    # Hapus dulu relasi anak di tabel clusters
    db.execute(
        text("DELETE FROM clusters WHERE daily_pengepul_id = :id"),
        {"id": id}
    )
    db.commit()

    # Lalu hapus parent
    entry = db.query(DailyPengepul).filter(DailyPengepul.id == id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Data pengepul tidak ditemukan.")

    db.delete(entry)
    db.commit()

    return JSONResponse(content={"message": "Data pengepul dan relasi clusters berhasil dihapus"})

