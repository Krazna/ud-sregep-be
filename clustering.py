from functools import lru_cache
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
    remaining_locations = sorted(locations[:], key=lambda l: l.sudut_polar, reverse=True)

    if not remaining_locations:
        return hasil_cluster, []

    current_date = remaining_locations[0].tanggal_cluster
    cluster_id_harian = 1

    while any(loc.nilai_ekspektasi_akhir > 0 and loc.status != "Sudah di-cluster" for loc in remaining_locations):
        while current_date.weekday() == 6:  # skip Minggu
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

                for loc in remaining_locations:
                    if (
                        loc.nilai_ekspektasi_akhir <= 0 or
                        loc.tanggal_cluster > current_date or
                        loc.status == "Sudah di-cluster"
                    ):
                        continue

                    if total_load >= kapasitas:
                        break

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
                break  # biar nggak infinite loop

        # Pindahkan sisa lokasi ke hari berikutnya
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

def build_distance_matrix(locations: List[dict]) -> dict[str, float]:
    coords = [(loc["longitude"], loc["latitude"]) for loc in locations]
    coords.insert(0, (DEPOT_LON, DEPOT_LAT))

    id_map = ["DEPOT"] + [str(loc["id"]) for loc in locations]
    matrix = {}

    for i in range(len(coords)):
        for j in range(len(coords)):
            if i == j:
                continue
            key = f"{id_map[i]}:{id_map[j]}"
            origin = coords[i]
            dest = coords[j]
            dist = cached_ors_request(origin, dest)
            matrix[key] = dist

    return matrix

def nearest_neighbor(locations: List[dict]):
    if not locations:
        return []

    distance_matrix = build_distance_matrix(locations)
    unvisited = locations[:]
    route = []
    current_id = "DEPOT"

    while unvisited:
        next_loc = min(
            unvisited,
            key=lambda loc: distance_matrix.get(f"{current_id}:{loc['id']}", float("inf"))
        )
        route.append(next_loc)
        current_id = str(next_loc["id"])
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
    clusters_existing = db.query(Cluster).join(DailyPengepul).filter(
        DailyPengepul.tanggal_cluster == tanggal
    ).all()

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
        # Kalau udah ada cluster dan gak ada data baru → tinggal tampilkan
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

    # Kalau ada cluster sebelumnya dan ada data baru → reset dan cluster ulang
    if clusters_existing and new_data_available:
        reset_daily_pengepul(tanggal, db)

    locations = db.query(DailyPengepul).filter(
        DailyPengepul.tanggal_cluster == tanggal
    ).order_by(DailyPengepul.sudut_polar).all()

    vehicles = db.query(Vehicle).order_by(Vehicle.kapasitas_kendaraan.desc()).all()

    if not locations or not vehicles:
        return standard_response(message="Data lokasi atau kendaraan kosong", status_code=400)

    hasil_cluster, _ = sweep_algorithm(locations, vehicles, db)
    db.commit()

    flat_data = []
    for cluster in hasil_cluster:
        for loc in cluster["locations"]:
            flat_data.append({
                **loc,
                "nilai_ekspektasi": float(loc.get("nilai_ekspektasi", 0.0)),
                "nilai_ekspektasi_awal": float(loc.get("nilai_ekspektasi_awal", loc.get("nilai_ekspektasi", 0.0))),
                "nilai_ekspektasi_akhir": float(loc.get("nilai_ekspektasi_akhir", 0.0)),
                "nilai_diangkut": float(loc.get("nilai_diangkut", 0.0)),
                "status": "Sudah di-cluster" if float(loc.get("nilai_ekspektasi_akhir", 0.0)) == 0 else "Belum di-cluster",
                "cluster_id": cluster["cluster_id"],
                "nama_kendaraan": cluster["nama_kendaraan"]
            })

    return standard_response(
        message=f"{len(flat_data)} data berhasil di-cluster!",
        data=flat_data
    )

@cluster_router.get("/generate-routes")
def generate_routes(tanggal: date = Query(...), db: Session = Depends(get_db)):
    from collections import defaultdict

    clusters = (
        db.query(Cluster)
        .filter(Cluster.tanggal_cluster == tanggal)
        .all()
    )

    if not clusters:
        return standard_response(message="Belum ada cluster untuk tanggal ini", status_code=400)

    # Buat mapping cluster_id ke Cluster.id (PK)
    cluster_pk_map = {}
    for c in clusters:
        if c.cluster_id not in cluster_pk_map:
            cluster_pk_map[c.cluster_id] = c.id

    # Hapus ClusterRoute hanya untuk cluster_id yang ada di tanggal ini
    cluster_pk_list = list(cluster_pk_map.values())
    db.query(ClusterRoute).filter(ClusterRoute.cluster_id.in_(cluster_pk_list)).delete(synchronize_session=False)
    db.commit()

    hasil_routes = []
    cluster_dict = defaultdict(list)
    for cl in clusters:
        cluster_dict[cl.cluster_id].append(cl)

    for cluster_id in sorted(cluster_dict.keys()):
        cluster_items = cluster_dict[cluster_id]
        route_list = []
        vehicle_id = cluster_items[0].vehicle_id
        vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
        cluster_pk = cluster_pk_map[cluster_id]

        lokasi_list = []
        for cl in cluster_items:
            lokasi_list.append({
                "cluster_entry_id": cl.id,  # Gunakan ID unik dari tabel Cluster
                "daily_pengepul_id": cl.daily_pengepul_id,
                "nama_pengepul": cl.nama_pengepul,
                "alamat": cl.alamat,
                "latitude": float(cl.latitude),
                "longitude": float(cl.longitude),
                "nilai_ekspektasi_awal": float(cl.nilai_ekspektasi_awal),
                "nilai_ekspektasi_akhir": float(cl.nilai_ekspektasi_akhir),
                "nilai_diangkut": float(cl.nilai_diangkut),
            })

        ordered_locations = nearest_neighbor(lokasi_list)

        total_waktu_list = []
        total_jarak_list = []
        total_nilai_angkut = 0.0

        for i in range(len(ordered_locations)):
            asal = {"latitude": DEPOT_LAT, "longitude": DEPOT_LON} if i == 0 else ordered_locations[i - 1]
            tujuan = ordered_locations[i]

            dur, dist = ors_directions_request(
                (asal["longitude"], asal["latitude"]),
                (tujuan["longitude"], tujuan["latitude"])
            )

            if dur is None or dist is None:
                travel_time = 0
                dist = 0
            else:
                red_light = calculate_red_light_time(dist)
                travel_time = dist / SPEED + red_light

            total_waktu = (travel_time + LOAD_UNLOAD_TIME) * 3600
            total_waktu_list.append(int(total_waktu))
            total_jarak_list.append(round(dist, 2))

        # Pulang ke depot
        last_location = ordered_locations[-1]
        dur_back, dist_back = ors_directions_request(
            (last_location["longitude"], last_location["latitude"]),
            (DEPOT_LON, DEPOT_LAT)
        )

        if dur_back is None or dist_back is None:
            travel_back_time = 0
            dist_back = 0
        else:
            red_light_back = calculate_red_light_time(dist_back)
            travel_back_time = dist_back / SPEED + red_light_back

        total_waktu_list.append(int((travel_back_time + LOAD_UNLOAD_TIME) * 3600))
        total_jarak_list.append(round(dist_back, 2))

        # Simpan ClusterRoute dan update Location.sudah_diambil
        for idx, loc in enumerate(ordered_locations):
            location_entry = db.query(Location).filter(Location.id == loc["daily_pengepul_id"]).first()
            if not location_entry:
                print(f"ERROR: Location ID {loc['daily_pengepul_id']} gak ketemu, skip insert cluster_route")
                continue

            daily_pengepul_entry = db.query(DailyPengepul).filter(DailyPengepul.id == loc["daily_pengepul_id"]).first()
            if not daily_pengepul_entry:
                print(f"ERROR: DailyPengepul ID {loc['daily_pengepul_id']} gak ketemu, skip insert cluster_route")
                continue

            db.add(ClusterRoute(
                cluster_id=cluster_pk,
                vehicle_id=vehicle_id,
                order_no=idx + 1,
                daily_pengepul_id=loc["daily_pengepul_id"],
                location_id=loc["daily_pengepul_id"],
                nama_pengepul=loc["nama_pengepul"],
                alamat=loc["alamat"],
                waktu_tempuh=total_waktu_list[idx],
                jarak_tempuh_km=total_jarak_list[idx],
                nilai_ekspektasi_awal=loc["nilai_ekspektasi_awal"],
                nilai_ekspektasi_akhir=loc["nilai_ekspektasi_akhir"],
                nilai_diangkut=loc["nilai_diangkut"],
                tanggal_cluster=tanggal
            ))

            location_entry.sudah_diambil = True
            total_nilai_angkut += loc["nilai_diangkut"]

            route_list.append({
                "order_no": idx + 1,
                "daily_pengepul_id": loc["daily_pengepul_id"],
                "nama_pengepul": loc["nama_pengepul"],
                "nama_kendaraan": vehicle.nama_kendaraan if vehicle else "",
                "total_waktu": format_waktu(total_waktu_list[idx] / 3600),
                "jarak_km": total_jarak_list[idx],
                "nilai_awal": loc["nilai_ekspektasi_awal"],
                "nilai_akhir": loc["nilai_ekspektasi_akhir"],
                "nilai_diangkut": loc["nilai_diangkut"],
                "alamat": loc["alamat"]
            })

        hasil_routes.append({
            "cluster_id": cluster_id,
            "vehicle_id": vehicle_id,
            "routes": route_list,
            "total_jarak_cluster_km": round(sum(total_jarak_list), 2),
            "total_waktu_cluster": format_waktu(sum(total_waktu_list) / 3600),
            "total_nilai_diangkut": total_nilai_angkut
        })

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"DB Commit Error: {e}")
        return standard_response(message=f"DB Commit Error: {e}", status_code=500)

    return standard_response(
        message="Routes berhasil di-generate!",
        data={
            "tanggal": tanggal.isoformat(),
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
            "alamat": r.alamat
        })

    return standard_response(
        message=message,
        data=data
    )
    