from datetime import date, datetime
from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Date, Enum, Float, ForeignKey, Text, Numeric
from sqlalchemy.orm import relationship
from database import Base
from geopy.distance import geodesic
from math import atan2, degrees, radians, sin, cos
from geopy import Point

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    nama = Column(String(100), nullable=False)
    posisi = Column(String(50), nullable=False)
    username = Column(String(50), unique=True, nullable=False)
    tanggal_lahir = Column(Date, nullable=False)
    jenis_kelamin = Column(Enum("Laki-laki", "Perempuan"), nullable=False)
    alamat = Column(String(255), nullable=False)
    alamat_domisili = Column(String(255), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    nomor_hp = Column(String(15), nullable=False)
    password_hash = Column(String(255), nullable=False)

class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    nama_pengepul = Column(String(100), nullable=False)
    alamat = Column(String(255), nullable=False)
    latitude = Column(Numeric(18, 15), nullable=False)
    longitude = Column(Numeric(18, 15), nullable=False)
    nilai_ekspektasi = Column(Float, nullable=False)
    sudut_polar = Column(Float, nullable=True)
    sudah_diambil = Column(Boolean, default=False, nullable=False)

    @staticmethod
    def calculate_polar_angle(latitude, longitude):
        pusat = Point(-7.735771367498664, 110.34369342557244)
        target = Point(float(latitude), float(longitude))

        lat1 = radians(pusat.latitude)
        lon1 = radians(pusat.longitude)
        lat2 = radians(target.latitude)
        lon2 = radians(target.longitude)

        dlon = lon2 - lon1

        x = sin(dlon) * cos(lat2)
        y = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon)

        initial_bearing = atan2(x, y)
        bearing = (degrees(initial_bearing) + 360) % 360

        return bearing

    @staticmethod
    def get_sudut_polar_from_latlon(lat, lon):
        return Location.calculate_polar_angle(lat, lon)

    @property
    def status_diambil(self):
        return "sudah diambil" if self.sudah_diambil else "belum diambil"
    
class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    nama_kendaraan = Column(String(100), nullable=False)
    kapasitas_kendaraan = Column(Integer, nullable=False)

    clusters = relationship("Cluster", back_populates="vehicle")
    cluster_routes = relationship("ClusterRoute", back_populates="vehicle")

class Cluster(Base):
    __tablename__ = "clusters"

    id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(Integer, nullable=False, index=True)

    daily_pengepul_id = Column(Integer, ForeignKey("daily_pengepul.id"), nullable=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False)

    tanggal_cluster = Column(Date, default=date.today, nullable=False)

    nama_pengepul = Column(String(255), nullable=True)
    alamat = Column(String(255), nullable=True)
    nilai_ekspektasi = Column(Float, nullable=True)
    latitude = Column(Numeric(18, 15), nullable=True)
    longitude = Column(Numeric(18, 15), nullable=True)

    nilai_ekspektasi_awal = Column(Float, nullable=True)
    nilai_ekspektasi_akhir = Column(Float, nullable=True)
    nilai_diangkut = Column(Float, nullable=True)  # ✅ Sudah dimasukkan

    # Relationship
    daily_pengepul = relationship("DailyPengepul", back_populates="clusters")
    vehicle = relationship("Vehicle", back_populates="clusters")

    # Cascade relationship ke ClusterRoute
    cluster_routes = relationship(
        "ClusterRoute",
        back_populates="cluster",
        cascade="all, delete-orphan"
    )

class ClusterRoute(Base):
    __tablename__ = "cluster_routes"

    id = Column(Integer, primary_key=True, index=True)

    cluster_id = Column(Integer, ForeignKey("clusters.cluster_id", ondelete="CASCADE"), nullable=False)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False)
    order_no = Column(Integer, nullable=False)

    daily_pengepul_id = Column(Integer, ForeignKey("daily_pengepul.id"), nullable=False)

    # 🆕 Tambahan location_id langsung dari daily_pengepul
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=True)

    nama_pengepul = Column(String(255), nullable=True)
    alamat = Column(String(255), nullable=True)

    waktu_tempuh = Column(String(255), nullable=True)
    jarak_tempuh_km = Column(Float, nullable=True)

    nilai_ekspektasi_awal = Column(Float, nullable=True)
    nilai_ekspektasi_akhir = Column(Float, nullable=True)
    nilai_diangkut = Column(Float, nullable=True)

    tanggal_cluster = Column(Date, default=date.today, nullable=False)

    # Relationships
    cluster = relationship("Cluster", back_populates="cluster_routes")
    vehicle = relationship("Vehicle", back_populates="cluster_routes")
    daily_pengepul = relationship("DailyPengepul", back_populates="cluster_routes")
    location = relationship("Location")  # Opsional kalau lo pengen akses .location langsung dari cluster_route

class DailyPengepul(Base):
    __tablename__ = "daily_pengepul"

    id = Column(Integer, primary_key=True, index=True)
    tanggal_cluster = Column(Date, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="RESTRICT"))  # ✅ prevent auto-delete
    nama_pengepul = Column(String(255))
    alamat = Column(String(255))
    nilai_ekspektasi = Column(Float, nullable=True)  # legacy, bisa dihapus kalau udah gak kepake
    nilai_ekspektasi_awal = Column(Float, nullable=True)
    nilai_ekspektasi_akhir = Column(Float, nullable=True)
    latitude = Column(Numeric(18, 15), nullable=True)
    longitude = Column(Numeric(18, 15), nullable=True)
    sudut_polar = Column(Float, nullable=True)

    # ✅ Kolom baru buat tracking status clustering
    status = Column(String(50), default="Belum di-cluster")

    location = relationship("Location", passive_deletes=True)
    clusters = relationship("Cluster", back_populates="daily_pengepul")
    cluster_routes = relationship("ClusterRoute", back_populates="daily_pengepul")
 
class DistanceMatrix(Base):
    __tablename__ = "distance_matrices"

    id = Column(Integer, primary_key=True, index=True)
    location_ids = Column(Text, nullable=False)
    matrix_data = Column(Text, nullable=False)

class TimeDistanceMatrix(Base):
    __tablename__ = "time_distance_matrix"

    id = Column(Integer, primary_key=True, index=True)
    location_ids = Column(Text)
    time_matrix = Column(Text)
    distance_matrix = Column(Text)

