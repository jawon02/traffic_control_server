from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 위에서 만든 라우터 파일 불러오기
from routers import monitor, control

app = FastAPI(
    title="Traffic Control API",
    version="1.0.0",
    description="비전 AI 기반 지능형 재난·사고 대응 교통 신호 제어 서버"
)

# 프론트엔드와 통신할 때 CORS 에러가 나지 않도록 허용해 주는 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 필요시 프론트엔드 주소 입력
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록 (이 부분이 있어야 위에서 만든 API들이 작동합니다)
app.include_router(monitor.router)
app.include_router(control.router)

@app.get("/")
def root():
    return {"message": "Traffic Control Backend Server is Running"}