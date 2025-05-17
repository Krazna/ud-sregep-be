from fastapi import Form
from pydantic import BaseModel, EmailStr
from datetime import date
from typing import Optional, List

class UserCreate(BaseModel):
    nama: str
    posisi: str
    username: str
    tanggal_lahir: date
    jenis_kelamin: str
    alamat: str
    alamat_domisili: str
    email: EmailStr
    nomor_hp: str
    password: str

class UserResponse(BaseModel):
    id: int
    nama: str
    posisi: str
    username: str
    email: str

    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    username: str
    password: str

    @classmethod
    def as_form(cls, username: str = Form(...), password: str = Form(...)):
        return cls(username=username, password=password)
    
class UserUpdate(BaseModel):
    nama: Optional[str] = None
    posisi: Optional[str] = None
    username: Optional[str] = None
    tanggal_lahir: Optional[date] = None
    jenis_kelamin: Optional[str] = None
    alamat: Optional[str] = None
    alamat_domisili: Optional[str] = None
    email: Optional[EmailStr] = None
    nomor_hp: Optional[str] = None
    password: Optional[str] = None


class LocationCreate(BaseModel):
    nama_pengepul: str
    alamat: str
    latitude: float
    longitude: float
    nilai_ekspektasi: float

    @classmethod
    def as_form(
        cls,
        nama_pengepul: str = Form(...),
        alamat: str = Form(...),
        latitude: float = Form(...),
        longitude: float = Form(...),
        nilai_ekspektasi: float = Form(...)
    ):
        return cls(
            nama_pengepul=nama_pengepul,
            alamat=alamat,
            latitude=latitude,
            longitude=longitude,
            nilai_ekspektasi=nilai_ekspektasi,
        )

class LocationResponse(BaseModel):
    id: int
    nama_pengepul: str
    alamat: str
    latitude: float
    longitude: float
    nilai_ekspektasi: float
    sudut_polar: float

    class Config:
        from_attributes = True

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
        from_attributes = True  # Pydantic v2
        orm_mode = True   

class DistanceMatrixCreate(BaseModel):
    location_ids: List[int]
    matrix: List[List[float]]

class DistanceMatrixResponse(BaseModel):
    id: int
    location_ids: List[int]
    matrix: List[List[float]]

    class Config:
        from_attributes = True

class ResponseWithMessage(BaseModel):
    message: str
    data: DistanceMatrixResponse

class PengepulItem(BaseModel):
    location_id: int
    nama_pengepul: str

class DailyPengepulCreate(BaseModel):
    tanggal_cluster: date
    pengepul_list: List[PengepulItem]

class DailyPengepulResponse(BaseModel):
    id: int
    tanggal_cluster: date
    location_id: int
    nama_pengepul: str
    alamat: Optional[str] = None 
    nilai_ekspektasi: Optional[float] = None 
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    sudut_polar: Optional[float] = None

    class Config:
        from_attributes = True


class LocationOut(BaseModel):
    id: int
    nama_pengepul: str
    nilai_ekspektasi: float
    alamat: str
    waktu_tempuh: str
    waktu_total: str
    jarak_tempuh_km: float

class ClusterOut(BaseModel):
    cluster_id: int
    vehicle_id: int
    nama_kendaraan: str
    total_waktu: str
    total_jarak_km: float
    locations: List[LocationOut]

class RouteLocationOut(BaseModel):
    daily_pengepul_id: int
    nama_pengepul: Optional[str]
    alamat: Optional[str]
    waktu_tempuh: Optional[str]
    jarak_tempuh_km: Optional[float]
    order_no: int

class ClusterRouteOut(BaseModel):
    cluster_id: int
    vehicle_id: int
    locations: List[RouteLocationOut]