from utils.routing import ors_directions_request
import time

# Constants
DEPOT_LAT = -7.735771367498664
DEPOT_LON = 110.34369342557244
DEPOT_COORD = (DEPOT_LON, DEPOT_LAT)

LOAD_UNLOAD_TIME = 0.75  # jam
MAX_HOURS = 8
SPEED = 40  # km/jam
RED_LIGHT_TIME = 0.0333  # jam


# Helpers
def format_waktu(jam: float) -> str:
    jam_int = int(jam)
    menit = int(round((jam - jam_int) * 60))
    return f"{jam_int}j {menit}m"

def calculate_red_light_time(distance_km: float) -> float:
    return (distance_km / 10) * RED_LIGHT_TIME

def calculate_travel_time(dist_km: float) -> float:
    """Travel time dalam jam termasuk red light penalty."""
    return dist_km / SPEED + calculate_red_light_time(dist_km)

def get_duration_distance(origin: tuple, destination: tuple) -> tuple:
    """Helper buat ambil durasi dan jarak ORS."""
    return ors_directions_request(origin, destination)


# Main Functions
def sweep_algorithm(locations, vehicles, depot=DEPOT_COORD, start_cluster_id=1):
    cluster_id = start_cluster_id
    vehicle_index = 0
    remaining_locations = locations[:]
    hasil_cluster = []

    while remaining_locations and vehicle_index < len(vehicles):
        vehicle = vehicles[vehicle_index]
        capacity = vehicle.kapasitas_kendaraan
        total_load = total_time = total_distance = 0.0
        prev_loc = None
        current_cluster = []
        used_locations = []

        for loc in remaining_locations:
            origin = depot if prev_loc is None else (prev_loc.longitude, prev_loc.latitude)
            destination = (loc.longitude, loc.latitude)

            dur, dist = get_duration_distance(origin, destination)
            if dur is None or dist is None:
                continue

            travel_time = calculate_travel_time(dist)
            waktu_di_lokasi = travel_time + LOAD_UNLOAD_TIME

            dur_back, dist_back = get_duration_distance(destination, depot)
            travel_back_time = calculate_travel_time(dist_back)

            simulasi_total_time = total_time + waktu_di_lokasi + travel_back_time

            nilai_ekspektasi = loc.location.nilai_ekspektasi 
            alamat = loc.location.alamat 

            if simulasi_total_time <= MAX_HOURS and total_load + nilai_ekspektasi <= capacity:
                current_cluster.append({
                    "id": loc.id,
                    "nama_pengepul": loc.nama_pengepul,
                    "nilai_ekspektasi": nilai_ekspektasi,  
                    "alamat": alamat,
                    "longitude": loc.longitude,
                    "latitude": loc.latitude,
                    "waktu_tempuh": format_waktu(travel_time),
                    "waktu_total": format_waktu(waktu_di_lokasi),
                    "jarak_tempuh_km": round(dist, 2),
                })
                used_locations.append(loc)
                total_load += nilai_ekspektasi
                total_time += waktu_di_lokasi
                total_distance += dist
                prev_loc = loc

        if not current_cluster:
            # >>> Tambahan fix: SKIP cluster kalau kosong
            vehicle_index += 1
            continue

        if used_locations:
            last = used_locations[-1]
            _, dist_back_last = get_duration_distance((last.longitude, last.latitude), depot)
            total_time += calculate_travel_time(dist_back_last)
            total_distance += dist_back_last

        hasil_cluster.append({
            "cluster_id": cluster_id,
            "vehicle_id": vehicle.id,
            "nama_kendaraan": vehicle.nama_kendaraan,
            "total_waktu": format_waktu(total_time),
            "total_jarak_km": round(total_distance, 2),
            "locations": current_cluster,
        })

        cluster_id += 1
        vehicle_index += 1
        remaining_locations = [loc for loc in remaining_locations if loc not in used_locations]

    return hasil_cluster

def nearest_neighbor_route(locations: list[dict], depot=DEPOT_COORD, cluster_id=None, vehicle_id=None):
    if not locations:
        return []

    if vehicle_id is None:
        raise ValueError("vehicle_id harus diisi untuk insert ke ClusterRoute!")

    remaining = locations[:]
    route = []
    current = {"longitude": depot[0], "latitude": depot[1]}
    order_no = 1

    while remaining:
        nearest = None
        nearest_dist = float('inf')

        for loc in remaining:
            dur, dist = get_duration_distance(
                (current["longitude"], current["latitude"]),
                (loc["longitude"], loc["latitude"])
            )
            if dist is not None and dist < nearest_dist:
                nearest = loc
                nearest_dist = dist

        if nearest is None:
            break

        route.append({
            "cluster_id": cluster_id,
            "vehicle_id": vehicle_id,
            "order_no": order_no,
            "daily_pengepul_id": nearest["id"],  # ini ID dari DailyPengepul
            "nama_pengepul": nearest.get("nama_pengepul") or "-",
            "alamat": nearest.get("alamat") or "-",
            "waktu_tempuh": nearest.get("waktu_tempuh") or "-",
            "jarak_tempuh_km": nearest.get("jarak_tempuh_km") or 0,
        })
        order_no += 1
        current = {"longitude": nearest["longitude"], "latitude": nearest["latitude"]}
        remaining.remove(nearest)

    return route
