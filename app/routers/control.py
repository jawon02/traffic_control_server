import base64
import asyncio
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.schemas.traffic import TrafficData, TrafficResponse
from app.services.logic import evaluate_traffic_control

router = APIRouter(prefix="/api/control", tags=["Control"])

# 프론트엔드 및 SUMO로 중계할 최신 전역 상태
latest_state = {
    "frame_bytes": None,
    "response": None,
    "data": None
}

@router.post("/", response_model=TrafficResponse)
def control_traffic(data: TrafficData):
    # 1. Base64 이미지 디코딩 후 바이트 형태로 메모리에 저장
    if data.image_frame:
        try:
            latest_state["frame_bytes"] = base64.b64decode(data.image_frame)
        except Exception as e:
            print(f"[ERROR] Frame decode failed: {e}")

    # 2. 신호 제어 알고리즘 수행 (east_cars, west_cars 추가)
    result = evaluate_traffic_control(
        pedestrian_count=data.pedestrian_count,
        exit_congested=data.exit_congested,
        accident_detected=data.accident_detected,
        emergency_detected=data.emergency_detected,
        north_cars=data.north_cars,
        south_cars=data.south_cars,
        east_cars=data.east_cars, # [추가]
        west_cars=data.west_cars  # [추가]
    )
    
    # 3. 최신 분석 데이터 수신 기록 저장
    latest_state["data"] = data.model_dump(exclude={"image_frame"}) # 이미지는 제외하고 저장
    latest_state["response"] = result
    return result

# ---------------------------------------------------------
# 프론트엔드 및 SUMO 연동 전용 API 엔드포인트
# ---------------------------------------------------------

# API 1: MJPEG 영상 스트리밍 주소 (DetailVideo.jsx 에서 사용)
@router.get("/stream")
async def video_stream():
    async def frame_generator():
        while True:
            if latest_state["frame_bytes"] is not None:
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + latest_state["frame_bytes"] + b'\r\n'
                )
            await asyncio.sleep(0.1)  # 10fps 주기로 프론트엔드 송출

    return StreamingResponse(
        frame_generator(), 
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

# API 2: 최신 전체 데이터 폴링 주소 (DetailPanel.jsx 및 SUMO 연동용)
@router.get("/latest")
def get_latest_traffic():
    if latest_state["response"] is None:
        return {"status": "WAITING", "message": "AI 분석 데이터 대기 중"}
    
    return {
        "status": "ACTIVE",
        "data": latest_state["data"],
        "result": latest_state["response"]
    }

# API 3: SUMO 기존 bridge.py 호환 전용 신호 데이터 조회 주소
@router.get("/signal")
def get_signal_status():
    if latest_state["response"] is None:
        return {"status": "WAITING", "message": "신호 제어 데이터 대기 중"}
    
    return {
        "status": "ACTIVE",
        "result": latest_state["response"]
    }