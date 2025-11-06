import os
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from bson import ObjectId
from jose import JWTError, jwt

from database import db, create_document, get_documents
from schemas import User, Course, Enrollment, Progress, Certificate

# JWT settings
SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

app = FastAPI(title="GetaiCertified API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"name": "GetaiCertified API", "status": "ok"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "❌ Not Set",
        "database_name": "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, "name") else "Unknown"
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:60]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:60]}"
    return response


# ---------- JWT helpers ----------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db["user"].find_one({"email": email}) if db else None
    if not user:
        raise credentials_exception
    return {k: v for k, v in user.items() if k != "_id"}


# ---------- Auth (email+code demo + Google stub) ----------
class SignupRequest(BaseModel):
    name: str
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    name: Optional[str] = None


class GoogleAuthRequest(BaseModel):
    id_token: str


@app.post("/api/auth/signup")
def signup(payload: SignupRequest):
    existing = db["user"].find_one({"email": payload.email}) if db else None
    if existing:
        token = create_access_token({"sub": existing.get("email")})
        return {"user": {"name": existing.get("name"), "email": existing.get("email"), "points": existing.get("points", 0), "badges": existing.get("badges", [])}, "token": token}

    user = User(name=payload.name, email=payload.email)
    _id = create_document("user", user)
    token = create_access_token({"sub": payload.email})
    return {"user": {**user.model_dump()}, "id": _id, "token": token}


@app.post("/api/auth/login", response_model=Token)
async def login(request: Request):
    # Accept either application/x-www-form-urlencoded (username) or JSON { email }
    email = None
    try:
        form = await request.form()
        email = form.get("username") or form.get("email")
    except Exception:
        pass
    if not email:
        try:
            body = await request.json()
            email = body.get("email")
        except Exception:
            email = None
    if not email:
        raise HTTPException(status_code=400, detail="Email required")

    existing = db["user"].find_one({"email": email}) if db else None
    if not existing:
        user = User(name=email.split("@")[0].title(), email=email)
        create_document("user", user)
    token = create_access_token({"sub": email})
    return Token(access_token=token)


@app.post("/api/auth/google")
def google_auth(body: GoogleAuthRequest):
    # In production, verify id_token with Google. Here we accept and mint JWT if email present in payload
    try:
        email = None
        if "@" in body.id_token:
            email = body.id_token.strip()
        if not email:
            raise ValueError("Invalid token")
        existing = db["user"].find_one({"email": email}) if db else None
        if not existing:
            user = User(name=email.split("@")[0].title(), email=email)
            create_document("user", user)
        token = create_access_token({"sub": email})
        return {"access_token": token, "token_type": "bearer"}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Google token")


@app.get("/api/me")
def me(current=Depends(get_current_user)):
    return current


# ---------- Courses ----------
@app.get("/api/courses", response_model=List[Course])
def list_courses():
    docs = get_documents("course") if db else []
    if not docs:
        return [
            Course(
                title="GetaiCertified 3-Week AI Program",
                slug="3-week-ai",
                description="Learn AI fundamentals, master 14+ tools, and ship a capstone.",
                tools=[
                    "ChatGPT",
                    "Midjourney",
                    "Runway",
                    "Notion AI",
                    "Claude",
                    "LangChain",
                ],
            )
        ]
    return [Course(**{k: v for k, v in d.items() if k != "_id"}) for d in docs]


# ---------- Enrollment / Progress ----------
class EnrollRequest(BaseModel):
    email: EmailStr
    course_slug: str


@app.post("/api/enroll")
def enroll(payload: EnrollRequest, current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    if current.get("email") != payload.email:
        raise HTTPException(status_code=403, detail="Email mismatch")
    db["enrollment"].update_one(
        {"user_email": payload.email, "course_slug": payload.course_slug},
        {"$setOnInsert": {"status": "enrolled"}},
        upsert=True,
    )
    db["progress"].update_one(
        {"user_email": payload.email, "course_slug": payload.course_slug},
        {"$setOnInsert": {"lessons_completed": [], "week_unlocked": 1, "xp": 0}},
        upsert=True,
    )
    return {"ok": True}


class ProgressUpdate(BaseModel):
    email: EmailStr
    course_slug: str
    lesson_id: str
    xp: int = 10


@app.post("/api/progress/complete")
def complete_lesson(body: ProgressUpdate, current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    if current.get("email") != body.email:
        raise HTTPException(status_code=403, detail="Email mismatch")
    db["progress"].update_one(
        {"user_email": body.email, "course_slug": body.course_slug},
        {
            "$addToSet": {"lessons_completed": body.lesson_id},
            "$inc": {"xp": body.xp},
        },
        upsert=True,
    )
    prog = db["progress"].find_one({"user_email": body.email, "course_slug": body.course_slug})
    lcount = len(prog.get("lessons_completed", [])) if prog else 0
    week_unlocked = min(3, 1 + lcount // 4)
    db["progress"].update_one(
        {"user_email": body.email, "course_slug": body.course_slug},
        {"$set": {"week_unlocked": week_unlocked}},
    )
    return {"ok": True, "week_unlocked": week_unlocked}


@app.get("/api/dashboard")
def dashboard(email: EmailStr, course_slug: str = "3-week-ai"):
    user = db["user"].find_one({"email": email}) if db else None
    progress = db["progress"].find_one({"user_email": email, "course_slug": course_slug}) if db else None
    leaderboard = (
        db["progress"].find({}, {"_id": 0, "user_email": 1, "xp": 1}).sort("xp", -1).limit(10)
        if db
        else []
    )
    lb = list(leaderboard) if leaderboard else []
    return {
        "user": {
            "name": (user or {}).get("name", "Learner"),
            "email": email,
            "points": (user or {}).get("points", (progress or {}).get("xp", 0)),
            "badges": (user or {}).get("badges", []),
        },
        "progress": {
            "lessons_completed": (progress or {}).get("lessons_completed", []),
            "week_unlocked": (progress or {}).get("week_unlocked", 1),
            "xp": (progress or {}).get("xp", 0),
        },
        "leaderboard": lb,
    }


# ---------- Certificate (stub) ----------
class CertRequest(BaseModel):
    email: EmailStr
    course_slug: str


@app.post("/api/certificate")
def issue_certificate(body: CertRequest, current=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    if current.get("email") != body.email:
        raise HTTPException(status_code=403, detail="Email mismatch")
    cert_id = str(ObjectId())
    db["certificate"].update_one(
        {"user_email": body.email, "course_slug": body.course_slug},
        {"$set": {"certificate_id": cert_id, "verified": True}},
        upsert=True,
    )
    return {"certificate_id": cert_id}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
