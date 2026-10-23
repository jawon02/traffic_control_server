import time # 서버 시작 시간 기록용
import logging # 에러 경고 메시지 기록 도구
from fastapi import FastAPI, Request, status # HTTP 상태 코드 정의용
from fastapi.middleware.cors import CORSMiddleware # CORS 설정용
from fastapi.exceptions import RequestValidationError # 데이터 형식 오류 처리용
from fastapi.responses import JSONResponse # JSON 응답용
from app.routers import monitor, control # 라우터 모듈 임포트

# 1. 로깅 설정 (서버 콘솔에 시간과 로그 레벨이 보기 좋게 찍히도록 설정)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("TrafficServer")

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

# 로깅 미들웨어: 모든 요청과 응답을 로깅하고 처리 시간을 측정
@app.middleware("http")
async def log_requests_and_responses(request: Request, call_next):
    start_time = time.time()
    
    # 요청 처리 진행
    response = await call_next(request)
    
    # 처리 소요 시간 계산 (ms 단위)
    process_time = (time.time() - start_time) * 1000
    
    # 콘솔에 직관적이고 예쁜 로그 출력
    logger.info(
        f"Method: {request.method} | Path: {request.url.path} | "
        f"Status: {response.status_code} | Duration: {process_time:.2f}ms"
    )
    
    return response

# 데이터 형식 오류 처리
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # 잘못된 데이터 규격이 들어왔을 때 서버가 안 죽고 경고 로그를 남김
    logger.warning(f"[Validation Error] 잘못된 데이터 형식 수신 (Client: {request.client.host}): {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "전송된 데이터의 형식(Schema)이나 타입이 올바르지 않습니다.",
            "received_errors": exc.errors()
        },
    )

# 서버 내부 오류 처리
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # 개발자가 예상치 못한 서버 내부 에러가 났을 때 서버가 뻗는 것을 방지
    logger.error(f"[Critical Error] 서버 내부 예기치 못한 에러 발생 (Path: {request.url.path}): {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "서버 내부 오류가 발생했습니다. 관리자에게 문의하세요.",
            "error_type": type(exc).__name__
        },
    )

# 라우터 등록
app.include_router(monitor.router)
app.include_router(control.router)

@app.get("/")
def root():
    return {"message": "Traffic Control Backend Server is Running Smoothly!"}