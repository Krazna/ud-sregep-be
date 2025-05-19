from functools import lru_cache
import os
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from models import DailyPengepul, Location, Vehicle, Cluster, ClusterRoute, TimeDistanceMatrix
from database import get_db
from fastapi.responses import JSONResponse
from utils.routing import ors_directions_request, precompute_matrix
import json
from datetime import date, datetime, timedelta
from collections import defaultdict
from typing import List, Optional
from sqlalchemy.orm import joinedload

cluster_router = APIRouter()

DEPOT_LAT = -7.735771367498664
DEPOT_LON = 110.34369342557244
LOAD_UNLOAD_TIME = 0.75  # 45 menit
MAX_HOURS = 8
SPEED = 40  # km/jam
RED_LIGHT_TIME = 0.0333  # 2 menit dalam jam


def format_waktu(jam: float) -> str:
    jam_int = int(jam)
    menit = int(round((jam - jam_int) * 60))
    return f"{jam_int}j {menit}m"


def calculate_red_light_time(distance_km: float) -> float:
    return (distance_km / 10) * RED_LIGHT_TIME


def standard_response(data=None, message: str = "Success", status_code: int = 200):
    return JSONResponse(status_code=status_code, content={"message": message, "data": data})

MAX_CLUSTER_PER_DAY = 3

def sweep_algorithm(locations: List[DailyPengepul], vehicles: List[Vehicle], db: Session):
    hasil_cluster = []
    # Urutkan berdasarkan sudut polar menurun
    remaining_locations = sorted(locations[:], key=lambda l: l.sudut_polar, reverse=True)

    if not remaining_locations:
        return hasil_cluster, []

    current_date = remaining_locations[0].tanggal_cluster
    cluster_id_harian = 1

    while any(loc.nilai_ekspektasi_akhir > 0 and loc.status != "Sudah di-cluster" for loc in remaining_locations):
        while current_date.weekday() == 6:  # Skip hari Minggu
            current_date += timedelta(days=1)

        print(f"\n📆 Mulai clustering tanggal: {current_date}")
        cluster_hari_ini = 0
        cluster_id_harian = 1

        while cluster_hari_ini < MAX_CLUSTER_PER_DAY:
            any_vehicle_used = False

            for vehicle in vehicles:
                kapasitas = vehicle.kapasitas_kendaraan
                total_load = total_time = total_distance = 0.0
                prev_loc = None
                current_cluster = []
                used_locations = []

                # Sort ulang berdasarkan sudut polar setiap loop kendaraan
                sorted_locations = sorted(
                    [loc for loc in remaining_locations if loc.nilai_ekspektasi_akhir > 0 and loc.status != "Sudah di-cluster" and loc.tanggal_cluster <= current_date],
                    key=lambda l: l.sudut_polar,
                    reverse=True
                )

                for loc in sorted_locations:
                    if total_load >= kapasitas:
                        break

                    # Hitung durasi dan jarak dari previous location atau depot
                    if prev_loc is None:
                        dur, dist = ors_directions_request((DEPOT_LON, DEPOT_LAT), (loc.longitude, loc.latitude))
                    else:
                        dur, dist = ors_directions_request((prev_loc.longitude, prev_loc.latitude), (loc.longitude, loc.latitude))

                    if dur is None or dist is None:
                        continue

                    red_light = calculate_red_light_time(dist)
                    travel_time = dist / SPEED + red_light
                    waktu_di_lokasi = travel_time + LOAD_UNLOAD_TIME

                    dur_back, dist_back = ors_directions_request((loc.longitude, loc.latitude), (DEPOT_LON, DEPOT_LAT))
                    if dur_back is None or dist_back is None:
                        continue

                    travel_back_time = dist_back / SPEED + calculate_red_light_time(dist_back)
                    simulasi_total_time = total_time + waktu_di_lokasi + travel_back_time

                    muatan_bisa_diangkut = min(kapasitas - total_load, loc.nilai_ekspektasi_akhir)

                    if simulasi_total_time <= MAX_HOURS and muatan_bisa_diangkut > 0:
                        nilai_awal = loc.nilai_ekspektasi_akhir
                        loc.nilai_ekspektasi_akhir -= muatan_bisa_diangkut
                        loc.tanggal_cluster = current_date
                        loc.status = "Sudah di-cluster" if loc.nilai_ekspektasi_akhir == 0 else "Belum di-cluster"
                        db.add(loc)

                        current_cluster.append({
                            "id": loc.id,
                            "nama_pengepul": loc.nama_pengepul,
                            "alamat": loc.alamat,
                            "nilai_ekspektasi": float(muatan_bisa_diangkut),
                            "nilai_ekspektasi_awal": float(nilai_awal),
                            "nilai_ekspektasi_akhir": float(loc.nilai_ekspektasi_akhir),
                            "nilai_diangkut": float(muatan_bisa_diangkut),
                            "status": loc.status,
                            "latitude": float(loc.latitude),
                            "longitude": float(loc.longitude),
                            "waktu_tempuh": format_waktu(travel_time),
                            "jarak_tempuh_km": round(float(dist), 2),
                        })

                        cluster = Cluster(
                            cluster_id=cluster_id_harian,
                            daily_pengepul_id=loc.id,
                            vehicle_id=vehicle.id,
                            nama_pengepul=loc.nama_pengepul,
                            alamat=loc.alamat,
                            nilai_ekspektasi=muatan_bisa_diangkut,
                            nilai_ekspektasi_awal=nilai_awal,
                            nilai_ekspektasi_akhir=loc.nilai_ekspektasi_akhir,
                            latitude=loc.latitude,
                            longitude=loc.longitude,
                            nilai_diangkut=muatan_bisa_diangkut,
                            tanggal_cluster=current_date
                        )
                        db.add(cluster)

                        total_load += muatan_bisa_diangkut
                        total_time += waktu_di_lokasi
                        total_distance += dist
                        used_locations.append(loc)
                        prev_loc = loc

                if used_locations:
                    last = used_locations[-1]
                    _, dist_back_last = ors_directions_request((last.longitude, last.latitude), (DEPOT_LON, DEPOT_LAT))
                    total_time += dist_back_last / SPEED + calculate_red_light_time(dist_back_last)
                    total_distance += dist_back_last

                    hasil_cluster.append({
                        "cluster_id": cluster_id_harian,
                        "vehicle_id": vehicle.id,
                        "nama_kendaraan": vehicle.nama_kendaraan,
                        "total_waktu": format_waktu(total_time),
                        "total_jarak_km": round(total_distance, 2),
                        "locations": current_cluster,
                    })

                    try:
                        db.commit()
                        any_vehicle_used = True
                        cluster_hari_ini += 1
                        cluster_id_harian += 1
                        print(f"✅ Cluster {cluster_id_harian-1} selesai dengan {len(current_cluster)} lokasi")
                        if cluster_hari_ini >= MAX_CLUSTER_PER_DAY:
                            print(f"⚠️ Max cluster per hari tercapai ({MAX_CLUSTER_PER_DAY})")
                            break
                    except Exception as e:
                        db.rollback()
                        print(f"❌ Gagal commit cluster_id {cluster_id_harian}: {str(e)}")
                        raise

            if not any_vehicle_used:
                print("⚠️ Tidak ada kendaraan yang bisa digunakan hari ini.")
                break

        # Update tanggal_cluster ke hari berikutnya jika belum ter-cluster
        for loc in remaining_locations:
            if loc.nilai_ekspektasi_akhir > 0 and loc.tanggal_cluster <= current_date and loc.status != "Sudah di-cluster":
                loc.tanggal_cluster = current_date + timedelta(days=1)
                db.add(loc)
        db.commit()

        current_date += timedelta(days=1)

    return hasil_cluster, []

@lru_cache(maxsize=1024)
def cached_ors_request(origin: tuple, dest: tuple) -> float:
    """Cached ORS request untuk jarak (km)"""
    _, dist = ors_directions_request(origin, dest)
    return dist or float("inf")

def build_distance_matrix(locations: List[dict]) -> dict:
    """Build distance matrix using OSRM cached durations."""
    matrix = {}
    depot = (
        float(os.getenv("DEPOT_LNG", "110.34369342557244")),
        float(os.getenv("DEPOT_LAT", "-7.735771367498664"))
    )

    for loc1 in locations:
        id1 = str(loc1.get("daily_pengepul_id") or loc1.get("id"))
        coord1 = (loc1["longitude"], loc1["latitude"])

        # From depot to loc1
        dur, _ = ors_directions_request(depot, coord1)
        if dur == 0:
            print(f"[WARNING] Durasi 0 dari DEPOT ke {id1}")
        matrix[f"DEPOT:{id1}"] = dur

        # From loc1 to depot
        dur, _ = ors_directions_request(coord1, depot)
        if dur == 0:
            print(f"[WARNING] Durasi 0 dari {id1} ke DEPOT")
        matrix[f"{id1}:DEPOT"] = dur

        for loc2 in locations:
            if loc1 == loc2:
                continue
            id2 = str(loc2.get("daily_pengepul_id") or loc2.get("id"))
            coord2 = (loc2["longitude"], loc2["latitude"])

            dur, _ = ors_directions_request(coord1, coord2)
            if dur == 0:
                print(f"[WARNING] Durasi 0 dari {id1} ke {id2}")
            matrix[f"{id1}:{id2}"] = dur

    return matrix

def nearest_neighbor(locations: List[dict], distance_matrix: dict) -> List[dict]:
    """Find optimized route using nearest neighbor based on provided distance matrix."""
    if not locations:
        return []

    unvisited = locations[:]
    route = []
    current_id = "DEPOT"

    while unvisited:
        next_loc = min(
            unvisited,
            key=lambda loc: distance_matrix.get(
                f"{current_id}:{str(loc.get('daily_pengepul_id') or loc.get('id'))}",
                float("inf")
            )
        )
        route.append(next_loc)
        current_id = str(next_loc.get("daily_pengepul_id") or next_loc.get("id"))
        unvisited.remove(next_loc)

    return route

def reset_daily_pengepul(tanggal: date, db: Session):
    # Hapus semua data Cluster di tanggal itu
    db.query(Cluster).filter(Cluster.tanggal_cluster == tanggal).delete(synchronize_session=False)

    # Reset data daily_pengepul di tanggal itu
    pengepuls = db.query(DailyPengepul).filter(DailyPengepul.tanggal_cluster == tanggal).all()
    for loc in pengepuls:
        loc.nilai_ekspektasi_akhir = loc.nilai_ekspektasi_awal
        loc.status = "Belum di-cluster"
        db.add(loc)

    db.commit()

@cluster_router.get("/clustering")
def sweep_clustering(tanggal: date = Query(...), db: Session = Depends(get_db)):
    # Cek apakah sudah pernah di-cluster
    clusters_existing = db.query(Cluster).join(DailyPengepul).filter(
        DailyPengepul.tanggal_cluster == tanggal
    ).order_by(Cluster.cluster_id, Cluster.sequence).all()  # <--- Urut berdasarkan cluster dan urutan

    existing_ids = set(
        r[0] for r in db.query(Cluster.daily_pengepul_id)
        .join(DailyPengepul)
        .filter(DailyPengepul.tanggal_cluster == tanggal)
        .all()
    )

    new_data_available = db.query(DailyPengepul).filter(
        DailyPengepul.tanggal_cluster == tanggal,
        ~DailyPengepul.id.in_(existing_ids)
    ).count() > 0

    if clusters_existing and not new_data_available:
        # Data lama → tinggal tampilkan
        flat_data = []
        for cluster in clusters_existing:
            loc = cluster.daily_pengepul
            flat_data.append({
                "id": loc.id,
                "nama_pengepul": loc.nama_pengepul,
                "alamat": loc.alamat,
                "nilai_ekspektasi": float(loc.nilai_ekspektasi or 0.0),
                "nilai_ekspektasi_awal": float(loc.nilai_ekspektasi_awal or 0.0),
                "nilai_ekspektasi_akhir": float(loc.nilai_ekspektasi_akhir or 0.0),
                "nilai_diangkut": float(cluster.nilai_diangkut or 0.0),
                "status": "Sudah di-cluster" if (loc.nilai_ekspektasi_akhir or 0.0) == 0 else "Belum di-cluster",
                "latitude": float(loc.latitude),
                "longitude": float(loc.longitude),
                "cluster_id": cluster.cluster_id,
                "nama_kendaraan": cluster.vehicle.nama_kendaraan if cluster.vehicle else None
            })
        return standard_response(
            message=f"{len(flat_data)} data hasil clustering ditemukan.",
            data=flat_data
        )

    # Kalau ada cluster lama + data baru → reset
    if clusters_existing and new_data_available:
        reset_daily_pengepul(tanggal, db)

    locations = db.query(DailyPengepul).filter(
        DailyPengepul.tanggal_cluster == tanggal
    ).order_by(DailyPengepul.sudut_polar).all()

    vehicles = db.query(Vehicle).order_by(Vehicle.kapasitas_kendaraan.desc()).all()

    if not locations or not vehicles:
        return standard_response(message="Data lokasi atau kendaraan kosong", status_code=400)

    hasil_cluster, _ = sweep_algorithm(locations, vehicles, db)

    # Simpan hasil clustering ke DB
    for cluster in hasil_cluster:
        for idx, loc in enumerate(cluster["locations"]):
            cluster_instance = Cluster(
                daily_pengepul_id=loc["id"],
                vehicle_id=cluster["vehicle_id"],
                nilai_diangkut=loc["nilai_diangkut"],
                cluster_id=cluster["cluster_id"],
                sequence=idx  # Simpan urutan kunjungan di sini
            )
            db.add(cluster_instance)
    db.commit()

    # Format hasil output
    flat_data = []
    for cluster in hasil_cluster:
        for idx, loc in enumerate(cluster["locations"]):
            flat_data.append({
                **loc,
                "nilai_ekspektasi": float(loc.get("nilai_ekspektasi", 0.0)),
                "nilai_ekspektasi_awal": float(loc.get("nilai_ekspektasi_awal", loc.get("nilai_ekspektasi", 0.0))),
                "nilai_ekspektasi_akhir": float(loc.get("nilai_ekspektasi_akhir", 0.0)),
                "nilai_diangkut": float(loc.get("nilai_diangkut", 0.0)),
                "status": "Sudah di-cluster" if float(loc.get("nilai_ekspektasi_akhir", 0.0)) == 0 else "Belum di-cluster",
                "cluster_id": cluster["cluster_id"],
                "nama_kendaraan": cluster["nama_kendaraan"],
                "sequence": idx
            })

    return standard_response(
        message=f"{len(flat_data)} data berhasil di-cluster!",
        data=flat_data
    )

@cluster_router.get("/generate-routes")
def generate_routes(
    tanggal: date = Query(...),
    optimize: bool = Query(default=True),
    db: Session = Depends(get_db)
):
    from collections import defaultdict

    print(f"\n[DEBUG] Param optimize = {optimize}")
    print(f"[DEBUG] Tanggal = {tanggal}")

    existing_routes = db.query(ClusterRoute).filter(
        ClusterRoute.tanggal_cluster == tanggal,
        ClusterRoute.is_optimized == optimize
    ).all()

    if existing_routes:
        print("[INFO] Route sudah tersedia, ambil dari DB")
        grouped = defaultdict(list)
        for r in existing_routes:
            grouped[r.cluster_id].append(r)

        hasil_routes = []
        for cluster_id, routes in grouped.items():
            rute_list = ["Depot"] + [r.nama_pengepul for r in routes] + ["Depot"]
            total_jarak = sum(r.jarak_tempuh_km for r in routes)
            total_waktu_menit = sum(float(r.waktu_tempuh.replace(" menit", "")) for r in routes)
            total_nilai = sum(r.nilai_diangkut for r in routes)

            hasil_routes.append({
                "cluster_id": cluster_id,
                "vehicle_id": routes[0].vehicle_id if routes else None,
                "rute": " -> ".join(rute_list),
                "total_jarak_cluster_km": round(total_jarak, 2),
                "total_waktu_cluster": f"{int(total_waktu_menit // 60)}j {int(total_waktu_menit % 60)}m",
                "total_nilai_diangkut": round(total_nilai, 2),
                "routes": [
                    {
                        "order_no": r.order_no,
                        "daily_pengepul_id": r.daily_pengepul_id,
                        "nama_pengepul": r.nama_pengepul,
                        "nama_kendaraan": r.vehicle.nama_kendaraan if r.vehicle else "-",
                        "total_waktu": f"{int(float(r.waktu_tempuh.replace(' menit', '')) // 60)}j {int(float(r.waktu_tempuh.replace(' menit', '')) % 60)}m",
                        "jarak_km": r.jarak_tempuh_km,
                        "nilai_awal": r.nilai_ekspektasi_awal,
                        "nilai_akhir": r.nilai_ekspektasi_akhir,
                        "nilai_diangkut": r.nilai_diangkut,
                        "alamat": r.alamat
                    }
                    for r in routes
                ]
            })

        return standard_response(
            message="Data route tersedia dan sudah diambil dari DB",
            data={
                "tanggal": tanggal.isoformat(),
                "is_optimized": optimize,
                "total_cluster": len(hasil_routes),
                "hasil_routes": hasil_routes
            }
        )

    # Kalau belum ada, generate baru
    clusters = db.query(Cluster).filter(Cluster.tanggal_cluster == tanggal).all()
    if not clusters:
        return standard_response("Belum ada cluster untuk tanggal ini", status_code=400)

    cluster_dict = defaultdict(list)
    cluster_pk_map = {}
    for c in clusters:
        cluster_dict[c.cluster_id].append(c)
        cluster_pk_map[c.cluster_id] = c.id

    db.query(ClusterRoute).filter(
        ClusterRoute.cluster_id.in_(cluster_pk_map.values())
    ).delete(synchronize_session=False)
    db.commit()

    hasil_routes = []

    for cluster_id, cluster_items in cluster_dict.items():
        print(f"[DEBUG] Proses cluster {cluster_id}")
        cluster_pk = cluster_pk_map[cluster_id]
        vehicle_id = cluster_items[0].vehicle_id

        lokasi_list = [{
            "id": cl.daily_pengepul_id,
            "cluster_entry_id": cl.id,
            "daily_pengepul_id": cl.daily_pengepul_id,
            "location_id": cl.daily_pengepul.location_id if cl.daily_pengepul else None,
            "nama_pengepul": cl.nama_pengepul,
            "alamat": cl.alamat,
            "latitude": float(cl.latitude),
            "longitude": float(cl.longitude),
            "nilai_ekspektasi_awal": float(cl.nilai_ekspektasi_awal),
            "nilai_ekspektasi_akhir": float(cl.nilai_ekspektasi_akhir),
            "nilai_diangkut": float(cl.nilai_diangkut)
        } for cl in cluster_items]

        dp_map = {
            dp.id: dp.sudut_polar
            for dp in db.query(DailyPengepul)
            .filter(DailyPengepul.id.in_([l["daily_pengepul_id"] for l in lokasi_list]))
            .all()
        }
        for loc in lokasi_list:
            loc["sudut_polar"] = dp_map.get(loc["daily_pengepul_id"], 0)

        distance_matrix = build_distance_matrix(lokasi_list)

        if optimize:
            ordered_locations = nearest_neighbor(lokasi_list, distance_matrix)
        else:
            ordered_locations = sorted(lokasi_list, key=lambda x: x["sudut_polar"], reverse=True)

        cluster_result = {
            "cluster_id": cluster_id,
            "vehicle_id": vehicle_id,
            "rute": "",
            "total_jarak_cluster_km": 0.0,
            "total_waktu_cluster": "0j 0m",
            "total_nilai_diangkut": 0.0,
            "routes": []
        }

        rute_str = ["Depot"]
        total_jarak = 0.0
        total_waktu_menit = 0.0
        total_nilai = 0.0
        previous_id = "DEPOT"

        for i, loc in enumerate(ordered_locations):
            current_id = str(loc["daily_pengepul_id"])
            key = f"{previous_id}:{current_id}"
            durasi_menit = distance_matrix.get(key, 0)
            jarak_km = durasi_menit * 40 / 60 / 1000  # asumsi 40km/h

            route = ClusterRoute(
                cluster_id=cluster_pk,
                vehicle_id=vehicle_id,
                order_no=i + 1,
                daily_pengepul_id=loc["daily_pengepul_id"],
                location_id=loc["location_id"],
                nama_pengepul=loc["nama_pengepul"],
                alamat=loc["alamat"],
                nilai_ekspektasi_awal=loc["nilai_ekspektasi_awal"],
                nilai_ekspektasi_akhir=loc["nilai_ekspektasi_akhir"],
                nilai_diangkut=loc["nilai_diangkut"],
                tanggal_cluster=tanggal,
                is_optimized=optimize,
                waktu_tempuh=f"{round(durasi_menit, 2)} menit",
                jarak_tempuh_km=round(jarak_km, 2),
            )
            db.add(route)

            cluster_result["routes"].append({
                "order_no": i + 1,
                "daily_pengepul_id": loc["daily_pengepul_id"],
                "nama_pengepul": loc["nama_pengepul"],
                "nama_kendaraan": "Kendaraan Placeholder",  # Ganti sesuai logika kendaraan lo
                "total_waktu": f"{int(durasi_menit // 60)}j {int(durasi_menit % 60)}m",
                "jarak_km": round(jarak_km, 2),
                "nilai_awal": loc["nilai_ekspektasi_awal"],
                "nilai_akhir": loc["nilai_ekspektasi_akhir"],
                "nilai_diangkut": loc["nilai_diangkut"],
                "alamat": loc["alamat"]
            })

            rute_str.append(loc["nama_pengepul"])
            total_jarak += jarak_km
            total_waktu_menit += durasi_menit
            total_nilai += loc["nilai_diangkut"]

            previous_id = current_id

        rute_str.append("Depot")
        cluster_result["rute"] = " -> ".join(rute_str)
        cluster_result["total_jarak_cluster_km"] = round(total_jarak, 2)
        cluster_result["total_waktu_cluster"] = f"{int(total_waktu_menit // 60)}j {int(total_waktu_menit % 60)}m"
        cluster_result["total_nilai_diangkut"] = round(total_nilai, 2)

        hasil_routes.append(cluster_result)

    db.commit()

    return standard_response(
        message="Route berhasil di-generate",
        data={
            "tanggal": tanggal.isoformat(),
            "is_optimized": optimize,
            "total_cluster": len(hasil_routes),
            "hasil_routes": hasil_routes
        }
    )

@cluster_router.get("/report-routes")
def get_cluster_routes(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    def parse_date(date_str: Optional[str]) -> Optional[date]:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else None
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid date format: {date_str}. Use YYYY-MM-DD.")

    start = parse_date(start_date)
    end = parse_date(end_date)

    query = db.query(ClusterRoute).options(joinedload(ClusterRoute.vehicle))

    if start and end:
        query = query.filter(ClusterRoute.tanggal_cluster.between(start, end))
        message = f"berhasil menampilkan data dari tanggal {start} sampai {end}"
    elif start:
        query = query.filter(ClusterRoute.tanggal_cluster >= start)
        message = f"berhasil menampilkan data dari tanggal {start} ke atas"
    elif end:
        query = query.filter(ClusterRoute.tanggal_cluster <= end)
        message = f"berhasil menampilkan data sampai tanggal {end}"
    else:
        message = "berhasil menampilkan semua data"

    data = []
    for r in query.all():
        data.append({
            "cluster_id": r.cluster_id,
            "tanggal_cluster": r.tanggal_cluster.strftime("%Y-%m-%d"),  # serialize date ke string
            "nama_pengepul": r.nama_pengepul,
            "nama_kendaraan": r.vehicle.nama_kendaraan if r.vehicle else "",
            "nilai_ekspektasi_awal": r.nilai_ekspektasi_awal,
            "nilai_ekspektasi_akhir": r.nilai_ekspektasi_akhir,
            "nilai_diangkut": r.nilai_diangkut,
            "alamat": r.alamat
        })

    return standard_response(
        message=message,
        data=data
    )
    