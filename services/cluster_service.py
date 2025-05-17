from models import Cluster, ClusterRoute

def save_clusters(db, clusters: list[dict]):
    for cluster in clusters:
        for loc in cluster["locations"]:
            db.add(
                Cluster(
                    cluster_id=cluster["cluster_id"],
                    daily_pengepul_id=loc["id"],
                    vehicle_id=cluster["vehicle_id"]
                )
            )
    db.commit()

def save_routes(db, routes: list[dict]):
    for cluster_route in routes:
        for loc in cluster_route["locations"]:
            db.add(
                ClusterRoute(
                    cluster_id=cluster_route["cluster_id"],
                    vehicle_id=cluster_route["vehicle_id"],
                    order_no=loc["order_no"],
                    daily_pengepul_id=loc["daily_pengepul_id"],
                    nama_pengepul=loc["nama_pengepul"],
                    alamat=loc["alamat"],
                    waktu_tempuh=loc["waktu_tempuh"],
                    jarak_tempuh_km=loc["jarak_tempuh_km"],
                )
            )
    db.commit()
