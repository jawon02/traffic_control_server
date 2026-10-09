from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import monitor, control

app = FastAPI(
    title="Traffic Control API",
    description="비전 AI 기반 지능형 재난·사고 대응 교통 신호 제어 서버",
    version="1.0.0"
)

# CORS 설정 (프론트엔드 통신용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(monitor.router)
app.include_router(control.router)

@app.get("/")
def root():
    return {"message": "Traffic Control Backend Server is Running Smoothly!"}