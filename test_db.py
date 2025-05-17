from database import engine

try:
    with engine.connect() as connection:
        print("✅ Koneksi ke MySQL berhasil!")
except Exception as e:
    print(f"❌ Gagal terhubung ke database: {e}")
