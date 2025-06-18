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

MAX_CLUSTER_PER_DAY = 3

def add_workdays(start_date, workdays):
    days_added = 0
    current = start_date
    while days_added < workdays:
        current += timedelta(days=1)
        if current.weekday() != 6:  # Bukan Minggu
            days_added += 1
    return current

def sweep_algorithm(locations: List[DailyPengepul], vehicles: List[Vehicle], db: Session):
    hasil_cluster = []
    remaining_locations = sorted(locations[:], key=lambda l: l.sudut_polar, reverse=True)

    if not remaining_locations:
        return hasil_cluster, []

    current_date = remaining_locations[0].tanggal_cluster
    max_end_date = add_workdays(current_date, 4)
    last_remaining = {}

    while any(loc.nilai_ekspektasi_akhir > 0 and loc.status != "Sudah di-cluster" for loc in remaining_locations):
        if current_date > max_end_date:
            print(f"⏹️ Maksimal 5 hari tercapai, stop di tanggal: {current_date}")
            break

        if current_date.weekday() == 6:  # skip Minggu
            current_date += timedelta(days=1)
            continue

        print(f"\n📆 Mulai clustering tanggal: {current_date}")
        print(f"📍 Total lokasi sisa: {len(remaining_locations)}")

        cluster_hari_ini = 0
        cluster_id_harian = 1
        used_ids_today = set()

        while cluster_hari_ini < MAX_CLUSTER_PER_DAY:
            any_vehicle_used = False

            for vehicle in vehicles:
                kapasitas = vehicle.kapasitas_kendaraan
                total_load = total_time = total_distance = 0.0
                prev_loc = None
                current_cluster = []
                used_locations = []

                sorted_locations = sorted(
                    [
                        loc for loc in remaining_locations
                        if loc.nilai_ekspektasi_akhir > 0 and
                        loc.status != "Sudah di-cluster" and
                        loc.tanggal_cluster <= current_date and
                        loc.id not in used_ids_today
                    ],
                    key=lambda l: l.sudut_polar,
                    reverse=True
                )

                if not sorted_locations:
                    continue

                for loc in sorted_locations:
                    nilai_awal = last_remaining.get(loc.id)
                    if nilai_awal is None:
                        nilai_awal = loc.nilai_ekspektasi_awal or loc.nilai_ekspektasi  # Handle null

                    if nilai_awal < 25:
                        continue  # Skip lokasi dengan sisa muatan < 25kg

                    start_coord = (prev_loc.longitude, prev_loc.latitude) if prev_loc else (DEPOT_LON, DEPOT_LAT)
                    end_coord = (loc.longitude, loc.latitude)
                    dur, dist = ors_directions_request(start_coord, end_coord)
                    if dur is None or dist is None:
                        continue

                    red_light = calculate_red_light_time(dist)
                    travel_time = dist / SPEED + red_light

                    muatan_bisa_diangkut = min(kapasitas - total_load, nilai_awal)
                    if muatan_bisa_diangkut <= 0:
                        continue

                    waktu_unload = ((muatan_bisa_diangkut / 20.0) * 4.26) / 60
                    waktu_di_lokasi = travel_time + waktu_unload

                    dur_back, dist_back = ors_directions_request(end_coord, (DEPOT_LON, DEPOT_LAT))
                    if dur_back is None or dist_back is None:
                        continue

                    travel_back_time = dist_back / SPEED + calculate_red_light_time(dist_back)
                    simulasi_total_time = total_time + waktu_di_lokasi + travel_back_time

                    nilai_akhir = nilai_awal - muatan_bisa_diangkut

                    if simulasi_total_time <= MAX_HOURS:
                        last_remaining[loc.id] = nilai_akhir

                        loc.nilai_ekspektasi_awal = nilai_awal
                        loc.nilai_diangkut = muatan_bisa_diangkut
                        loc.nilai_ekspektasi_akhir = nilai_akhir
                        loc.tanggal_cluster = current_date
                        loc.status = "Sudah di-cluster" if nilai_akhir == 0 else "Belum di-cluster"
                        db.add(loc)

                        current_cluster.append({
                            "id": loc.id,
                            "nama_pengepul": loc.nama_pengepul,
                            "alamat": loc.alamat,
                            "nilai_ekspektasi": float(loc.nilai_ekspektasi),
                            "nilai_ekspektasi_awal": float(nilai_awal),
                            "nilai_diangkut": float(muatan_bisa_diangkut),
                            "nilai_ekspektasi_akhir": float(nilai_akhir),
                            "status": loc.status,
                            "latitude": float(loc.latitude),
                            "longitude": float(loc.longitude),
                            "waktu_tempuh": format_waktu(travel_time),
                            "jarak_tempuh_km": round(float(dist), 2),
                        })

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

                    for idx, loc in enumerate(used_locations):
                        if (loc.id, cluster_id_harian, current_date) in used_ids_today:
                            continue

                        existing = db.query(Cluster).filter_by(
                            daily_pengepul_id=loc.id,
                            tanggal_cluster=current_date,
                            cluster_id=cluster_id_harian
                        ).first()
                        if existing:
                            continue

                        cluster = Cluster(
                            cluster_id=cluster_id_harian,
                            daily_pengepul_id=loc.id,
                            vehicle_id=vehicle.id,
                            nama_pengepul=loc.nama_pengepul,
                            alamat=loc.alamat,
                            nilai_ekspektasi=loc.nilai_ekspektasi,
                            nilai_ekspektasi_awal=loc.nilai_ekspektasi_awal,
                            nilai_ekspektasi_akhir=loc.nilai_ekspektasi_akhir,
                            latitude=loc.latitude,
                            longitude=loc.longitude,
                            nilai_diangkut=loc.nilai_diangkut,
                            tanggal_cluster=current_date,
                            sequence=idx
                        )
                        db.add(cluster)
                        used_ids_today.add((loc.id, cluster_id_harian, current_date))

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
                    except Exception as e:
                        db.rollback()
                        raise

            if not any_vehicle_used:
                break

        for loc in remaining_locations:
            if loc.nilai_ekspektasi_akhir > 0 and loc.tanggal_cluster <= current_date and loc.status != "Sudah di-cluster":
                new_date = current_date + timedelta(days=1)
                while new_date.weekday() == 6:
                    new_date += timedelta(days=1)
                loc.tanggal_cluster = new_date
                db.add(loc)
        db.commit()

        next_date = current_date + timedelta(days=1)
        while next_date.weekday() == 6:
            next_date += timedelta(days=1)
        current_date = next_date

    return hasil_cluster, []

@lru_cache(maxsize=1024)
def cached_ors_request(origin: tuple, dest: tuple) -> float:
    """Cached ORS request untuk jarak (km)"""
    _, dist = ors_directions_request(origin, dest)
    return dist or float("inf")

def build_distance_matrix(locations: List[dict]) -> dict:
    """Build distance matrix using OSRM cached durations."""
    matrix = {}
    depot = (DEPOT_LON, DEPOT_LAT)
    
    for loc1 in locations:
        id1 = str(loc1.get("daily_pengepul_id") or loc1.get("id"))
        coord1 = (loc1["longitude"], loc1["latitude"])
        
        # From depot to loc1
        dur, _ = ors_directions_request(depot, coord1)
        matrix[f"DEPOT:{id1}"] = dur
        
        # From loc1 to depot
        dur, _ = ors_directions_request(coord1, depot)
        matrix[f"{id1}:DEPOT"] = dur
        
        for loc2 in locations:
            if loc1 == loc2:
                continue
            id2 = str(loc2.get("daily_pengepul_id") or loc2.get("id"))
            coord2 = (loc2["longitude"], loc2["latitude"])
            dur, _ = ors_directions_request(coord1, coord2)
            matrix[f"{id1}:{id2}"] = dur
    return matrix

def nearest_neighbor(locations: List[dict]) -> List[dict]:
    """Find optimized route based on OSRM travel time (duration)."""
    if not locations:
        return []

    distance_matrix = build_distance_matrix(locations)
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
    ).order_by(Cluster.cluster_id, Cluster.sequence).all()

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
        # Tampilkan data cluster lama
        flat_data = []
        for cluster in clusters_existing:
            loc = cluster.daily_pengepul
            nilai_diangkut = float(cluster.nilai_diangkut or 0.0)
            # Hitung waktu unload ulang (jika perlu ditampilkan)
            waktu_unload = ((nilai_diangkut / 20.0) * 4.26) / 60
            flat_data.append({
                "id": loc.id,
                "nama_pengepul": loc.nama_pengepul,
                "alamat": loc.alamat,
                "nilai_ekspektasi": float(loc.nilai_ekspektasi or 0.0),
                "nilai_ekspektasi_awal": float(loc.nilai_ekspektasi_awal or 0.0),
                "nilai_ekspektasi_akhir": float(loc.nilai_ekspektasi_akhir or 0.0),
                "nilai_diangkut": nilai_diangkut,
                "status": "Sudah di-cluster" if (loc.nilai_ekspektasi_akhir or 0.0) == 0 else "Belum di-cluster",
                "latitude": float(loc.latitude),
                "longitude": float(loc.longitude),
                "cluster_id": cluster.cluster_id,
                "nama_kendaraan": cluster.vehicle.nama_kendaraan if cluster.vehicle else None,
                "waktu_unload": format_waktu(waktu_unload),
                "total_waktu_lokasi": None  # Tidak bisa dihitung akurat dari data lama
            })
        return standard_response(
            message=f"{len(flat_data)} data hasil clustering ditemukan.",
            data=flat_data
        )

    # Kalau ada cluster lama + data baru → reset
    if clusters_existing and new_data_available:
        reset_daily_pengepul(tanggal, db)

    # Mulai proses clustering
    locations = db.query(DailyPengepul).filter(
        DailyPengepul.tanggal_cluster == tanggal
    ).order_by(DailyPengepul.sudut_polar).all()

    vehicles = db.query(Vehicle).order_by(Vehicle.kapasitas_kendaraan.desc()).all()

    if not locations or not vehicles:
        return standard_response(message="Data lokasi atau kendaraan kosong", status_code=400)

    hasil_cluster, _ = sweep_algorithm(locations, vehicles, db)

    # Format output (tanpa simpan ulang ke DB)
    flat_data = []
    for cluster in hasil_cluster:
        for idx, loc in enumerate(cluster["locations"]):
            nilai_diangkut = float(loc.get("nilai_diangkut", 0.0))
            waktu_unload = ((nilai_diangkut / 20.0) * 4.26) / 60
            travel_time = None
            try:
                travel_time = float(loc.get("jarak_tempuh_km", 0.0)) / SPEED + calculate_red_light_time(float(loc.get("jarak_tempuh_km", 0.0)))
            except:
                pass
            total_waktu_lokasi = travel_time + waktu_unload if travel_time is not None else None

            flat_data.append({
                **loc,
                "nilai_ekspektasi": float(loc.get("nilai_ekspektasi", 0.0)),
                "nilai_ekspektasi_awal": float(loc.get("nilai_ekspektasi_awal", loc.get("nilai_ekspektasi", 0.0))),
                "nilai_ekspektasi_akhir": float(loc.get("nilai_ekspektasi_akhir", 0.0)),
                "nilai_diangkut": nilai_diangkut,
                "status": "Sudah di-cluster" if float(loc.get("nilai_ekspektasi_akhir", 0.0)) == 0 else "Belum di-cluster",
                "cluster_id": cluster["cluster_id"],
                "nama_kendaraan": cluster["nama_kendaraan"],
                "sequence": idx,
                "waktu_unload": format_waktu(waktu_unload),
                "total_waktu_lokasi": format_waktu(total_waktu_lokasi) if total_waktu_lokasi is not None else None
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

    clusters = db.query(Cluster).filter(Cluster.tanggal_cluster == tanggal).all()
    if not clusters:
        return standard_response(message="Belum ada cluster untuk tanggal ini", status_code=400)

    existing_routes = db.query(ClusterRoute).filter(
        ClusterRoute.tanggal_cluster == tanggal,
        ClusterRoute.is_optimized == optimize
    ).all()

    print(f"[DEBUG] Found {len(existing_routes)} existing ClusterRoute (is_optimized={optimize})")

    if existing_routes:
        hasil_routes = []
        cluster_group = defaultdict(list)
        for cr in existing_routes:
            cluster_group[cr.cluster_id].append(cr)

        for cluster_id, routes in cluster_group.items():
            vehicle_id = routes[0].vehicle_id
            vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

            route_list = []
            total_nilai = 0.0
            total_waktu = 0
            total_jarak = 0.0
            rute = ["Depot"]

            for r in routes:
                total_nilai += r.nilai_diangkut or 0
                total_waktu += int(r.waktu_tempuh or 0)
                total_jarak += float(r.jarak_tempuh_km or 0)
                rute.append(r.nama_pengepul or "Pengepul")

                route_list.append({
                    "order_no": r.order_no,
                    "daily_pengepul_id": r.daily_pengepul_id,
                    "nama_pengepul": r.nama_pengepul,
                    "nama_kendaraan": vehicle.nama_kendaraan if vehicle else "",
                    "total_waktu": format_waktu(int(r.waktu_tempuh) / 3600),
                    "jarak_km": r.jarak_tempuh_km,
                    "nilai_awal": r.nilai_ekspektasi_awal,
                    "nilai_akhir": r.nilai_ekspektasi_akhir,
                    "nilai_diangkut": r.nilai_diangkut,
                    "alamat": r.alamat
                })

            rute.append("Depot")
            hasil_routes.append({
                "cluster_id": cluster_id,
                "vehicle_id": vehicle_id,
                "routes": route_list,
                "rute": " -> ".join(rute),
                "total_jarak_cluster_km": round(total_jarak, 2),
                "total_waktu_cluster": format_waktu(total_waktu / 3600),
                "total_nilai_diangkut": total_nilai
            })

        return standard_response(
            message="Data existing berhasil diambil (tidak regenerate)",
            data={
                "tanggal": tanggal.isoformat(),
                "is_optimized": optimize,
                "total_cluster": len(hasil_routes),
                "hasil_routes": hasil_routes
            }
        )

    cluster_pk_map = {c.cluster_id: c.id for c in clusters}
    cluster_pk_list = list(cluster_pk_map.values())
    db.query(ClusterRoute).filter(ClusterRoute.cluster_id.in_(cluster_pk_list)).delete(synchronize_session=False)
    db.commit()
    print(f"[DEBUG] Deleted old ClusterRoute for tanggal={tanggal}")

    hasil_routes = []
    cluster_dict = defaultdict(list)
    for cl in clusters:
        cluster_dict[cl.cluster_id].append(cl)

    for cluster_id in sorted(cluster_dict.keys()):
        print(f"\n[DEBUG] Processing cluster_id={cluster_id}")
        cluster_items = cluster_dict[cluster_id]
        vehicle_id = cluster_items[0].vehicle_id
        vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
        cluster_pk = cluster_pk_map[cluster_id]

        lokasi_list = []
        for cl in cluster_items:
            if cl.latitude is None or cl.longitude is None:
                print(f"[WARNING] Skipping daily_pengepul_id={cl.daily_pengepul_id} karena latitude/longitude kosong")
                continue

            lokasi_list.append({
                "id": cl.daily_pengepul_id,
                "cluster_entry_id": cl.id,
                "daily_pengepul_id": cl.daily_pengepul_id,
                "nama_pengepul": cl.nama_pengepul,
                "alamat": cl.alamat,
                "latitude": float(cl.latitude),
                "longitude": float(cl.longitude),
                "nilai_ekspektasi_awal": float(cl.nilai_ekspektasi_awal),
                "nilai_ekspektasi_akhir": float(cl.nilai_ekspektasi_akhir),
                "nilai_diangkut": float(cl.nilai_diangkut)
            })

        dp_map = {
            dp.id: dp.sudut_polar
            for dp in db.query(DailyPengepul)
            .filter(DailyPengepul.id.in_([loc["daily_pengepul_id"] for loc in lokasi_list]))
            .all()
        }

        for loc in lokasi_list:
            loc["sudut_polar"] = dp_map.get(loc["daily_pengepul_id"], 0)

        if optimize:
            print("[DEBUG] Sorting with Nearest Neighbor (optimize=True)")
            try:
                ordered_locations = nearest_neighbor(lokasi_list)
            except Exception as e:
                print(f"[ERROR] nearest_neighbor error for cluster {cluster_id}: {e}")
                continue
        else:
            print("[DEBUG] Sorting dengan sudut polar (optimize=False)")
            ordered_locations = sorted(lokasi_list, key=lambda x: x["sudut_polar"], reverse=True)

        if not ordered_locations:
            continue

        total_waktu_list = []
        total_jarak_list = []
        total_nilai_angkut = 0.0
        rute = ["Depot"]
        route_list = []

        for i in range(len(ordered_locations)):
            asal = {"latitude": DEPOT_LAT, "longitude": DEPOT_LON} if i == 0 else ordered_locations[i - 1]
            tujuan = ordered_locations[i]

            dur, dist = ors_directions_request(
                (asal["longitude"], asal["latitude"]),
                (tujuan["longitude"], tujuan["latitude"])
            )

            red_light = calculate_red_light_time(dist or 0)
            travel_time = (dist or 0) / SPEED + red_light if dist else 0

            nilai_diangkut = tujuan["nilai_diangkut"]
            unload_time = (nilai_diangkut / 20) * 4.26 * 60  # detik
            total_waktu = travel_time * 3600 + unload_time

            total_waktu_list.append(int(total_waktu))
            total_jarak_list.append(round(dist or 0, 2))

        last_location = ordered_locations[-1]
        dur_back, dist_back = ors_directions_request(
            (last_location["longitude"], last_location["latitude"]),
            (DEPOT_LON, DEPOT_LAT)
        )

        red_light_back = calculate_red_light_time(dist_back or 0)
        travel_back_time = (dist_back or 0) / SPEED + red_light_back if dist_back else 0

        total_waktu_list.append(int((travel_back_time + LOAD_UNLOAD_TIME) * 3600))
        total_jarak_list.append(round(dist_back or 0, 2))

        for idx, loc in enumerate(ordered_locations):
            daily_pengepul_entry = db.query(DailyPengepul).filter(DailyPengepul.id == loc["daily_pengepul_id"]).first()
            if not daily_pengepul_entry:
                print(f"[WARNING] DailyPengepul ID={loc['daily_pengepul_id']} not found, skip.")
                continue

            location_entry = db.query(Location).filter(Location.id == daily_pengepul_entry.location_id).first()
            if not location_entry:
                print(f"[WARNING] Location ID={daily_pengepul_entry.location_id} not found, skip update.")
            else:
                location_entry.sudah_diambil = True

            db.add(ClusterRoute(
                cluster_id=cluster_pk,
                vehicle_id=vehicle_id,
                order_no=idx + 1,
                daily_pengepul_id=loc["daily_pengepul_id"],
                location_id=daily_pengepul_entry.location_id if daily_pengepul_entry else None,
                nama_pengepul=loc["nama_pengepul"],
                alamat=loc["alamat"],
                waktu_tempuh=total_waktu_list[idx],
                jarak_tempuh_km=total_jarak_list[idx],
                nilai_ekspektasi_awal=loc["nilai_ekspektasi_awal"],
                nilai_ekspektasi_akhir=loc["nilai_ekspektasi_akhir"],
                nilai_diangkut=loc["nilai_diangkut"],
                tanggal_cluster=tanggal,
                is_optimized=optimize
            ))

            print(f"[DEBUG] INSERT route {idx+1} | is_optimized={optimize} | daily_pengepul_id={loc['daily_pengepul_id']}")

            total_nilai_angkut += loc["nilai_diangkut"]
            rute.append(loc["nama_pengepul"])

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

        rute.append("Depot")
        hasil_routes.append({
            "cluster_id": cluster_id,
            "vehicle_id": vehicle_id,
            "routes": route_list,
            "rute": " -> ".join(rute),
            "total_jarak_cluster_km": round(sum(total_jarak_list), 2),
            "total_waktu_cluster": format_waktu(sum(total_waktu_list) / 3600),
            "total_nilai_diangkut": total_nilai_angkut
        })

    try:
        db.commit()
        print("[DEBUG] DB Commit berhasil")
    except Exception as e:
        db.rollback()
        print(f"[ERROR] DB Commit error: {e}")
        return standard_response(message=f"DB Commit Error: {e}", status_code=500)

    return standard_response(
        message="Routes berhasil di-generate!",
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
            "tanggal_cluster": r.tanggal_cluster.strftime("%Y-%m-%d"),
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
    