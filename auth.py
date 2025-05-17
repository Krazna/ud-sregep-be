from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy.orm import Session
from models import User
from database import get_db
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta
from schemas import UserCreate, UserLogin, UserResponse, UserUpdate
from fastapi.security import OAuth2PasswordBearer
from typing import List
from fastapi import Query

auth_router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

SECRET_KEY = "rahasia123"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

token_blacklist = set()

def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Token tidak valid")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token tidak valid")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    return user

@auth_router.post("/register")
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(status_code=400, detail="Username sudah digunakan")
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(status_code=400, detail="Email sudah digunakan")

    hashed_pw = hash_password(user_data.password)
    
    # Buat dictionary dari user_data, lalu buang field 'password'
    user_dict = user_data.dict()
    user_dict.pop("password", None)
    
    # Buat user baru dengan password_hash
    user = User(**user_dict, password_hash=hashed_pw)
    
    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "message": "Registrasi berhasil",
        "data": {
            "id": user.id,
            "username": user.username
        }
    }

@auth_router.post("/login")
def login(form_data: UserLogin = Depends(UserLogin.as_form), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Username atau password salah")

    token_data = {"sub": str(user.id)}
    token = create_access_token(token_data)
    return {
        "message": "Login berhasil",
        "data": {
            "token": token,
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "posisi": user.posisi
        }
    }

@auth_router.post("/logout")
def logout(token: str = Depends(oauth2_scheme)):
    token_blacklist.add(token)
    return {"message": "Logout berhasil", "data": None}

@auth_router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "message": "Data user saat ini berhasil diambil",
        "data": {
            "id": current_user.id,
            "username": current_user.username,
            "email": current_user.email,
            "posisi": current_user.posisi
        }
    }

@auth_router.get("/users")
def get_all_users(
    db: Session = Depends(get_db),
    keyword: str = Query(None),
    limit: int = Query(10, ge=1),
    offset: int = Query(0, ge=0)
):
    query = db.query(User)

    if keyword:
        keyword_filter = f"%{keyword}%"
        query = query.filter(
            (User.username.ilike(keyword_filter)) |
            (User.email.ilike(keyword_filter)) |
            (User.nama.ilike(keyword_filter))
        )

    users = query.offset(offset).limit(limit).all()

    return {
        "message": "Data user berhasil diambil",
        "data": [
            {
                "id": user.id,
                "username": user.username,
                "nama": user.nama,
                "email": user.email,
                "nomor_hp": user.nomor_hp,
                "posisi": user.posisi
            }
            for user in users
        ]
    }

@auth_router.get("/users/{user_id}")
def get_user_by_id(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    return {
        "message": "Detail user berhasil diambil",
        "data": {
                "id": user.id,
                "nama": user.nama,
                "username": user.username,
                "email": user.email,
                "posisi": user.posisi,
                "tanggal_lahir": user.tanggal_lahir,
                "jenis_kelamin": user.jenis_kelamin,
                "alamat": user.alamat,
                "alamat_domisili": user.alamat_domisili,
                "nomor_hp": user.nomor_hp,
            }
    }

@auth_router.put("/users/{user_id}")
def update_user_by_id(user_id: int, update_data: UserUpdate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    if update_data.username and update_data.username != user.username:
        if db.query(User).filter(User.username == update_data.username).first():
            raise HTTPException(status_code=400, detail="Username sudah digunakan")

    if update_data.email and update_data.email != user.email:
        if db.query(User).filter(User.email == update_data.email).first():
            raise HTTPException(status_code=400, detail="Email sudah digunakan")

    for field, value in update_data.dict(exclude_unset=True).items():
        if field == "password":
            setattr(user, "password_hash", hash_password(value))
        else:
            setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return {
        "message": "User berhasil diperbarui",
        "data": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "posisi": user.posisi
        }
    }

@auth_router.delete("/users/{user_id}")
def delete_user_by_id(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    db.delete(user)
    db.commit()
    return {
        "message": f"User dengan ID {user_id} berhasil dihapus",
        "data": None
    }
