import base64
import asyncio
from typing import Dict, Tuple
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from app.schemas.traffic import TrafficData, TrafficResponse
from app.services.logic import evaluate_traffic_control

router = APIRouter(prefix="/api/control", tags=["Control"])

# 카메라별 최신 전역 상태 저장소 (Key: (intersection_id, camera_id))
camera_states: Dict[Tuple[int, int], dict] = {}


@router.post("/", response_model=TrafficResponse)
def control_traffic(data: TrafficData):
    # 1. 교차로 및 카메라 ID 추출 (pydantic 스키마 미수정 시에도 안전하게 동작하도록 getattr 적용)
    intersection_id = getattr(data, "intersection_id", 1)
    camera_id = getattr(data, "camera_id", 1)
    key = (intersection_id, camera_id)

    if key not in camera_states:
        camera_states[key] = {
            "frame_bytes": None,
            "response": None,
            "data": None
        }

    # 2. Base64 이미지 디코딩 후 바이트 형태로 저장
    if data.image_frame:
        try:
            camera_states[key]["frame_bytes"] = base64.b64decode(data.image_frame)
        except Exception as e:
            print(f"[ERROR] Frame decode failed (intersection {intersection_id}, cam {camera_id}): {e}")

    # 3. 신호 제어 알고리즘 수행
    result = evaluate_traffic_control(
        pedestrian_count=data.pedestrian_count,
        exit_congested=data.exit_congested,
        accident_detected=data.accident_detected,
        emergency_detected=data.emergency_detected,
        north_cars=data.north_cars,
        south_cars=data.south_cars,
        east_cars=data.east_cars,
        west_cars=data.west_cars
    )

    # 4. 최신 분석 데이터 및 신호 제어 결과 기록 (이미지 제외)
    dump_data = data.model_dump(exclude={"image_frame"}) if hasattr(data, "model_dump") else data.dict(exclude={"image_frame"})
    camera_states[key]["data"] = dump_data
    camera_states[key]["response"] = result

    return result


# ---------------------------------------------------------
# 프론트엔드 및 SUMO 연동 전용 API 엔드포인트
# ---------------------------------------------------------

# API 1: MJPEG 영상 스트리밍 주소 (카메라별)
# 사용예: GET /api/control/stream?intersection_id=1&camera_id=1
@router.get("/stream")
async def video_stream(intersection_id: int = Query(1), camera_id: int = Query(1)):
    key = (intersection_id, camera_id)

    async def frame_generator():
        while True:
            state = camera_states.get(key)
            if state and state.get("frame_bytes") is not None:
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + state["frame_bytes"] + b'\r\n'
                )
            await asyncio.sleep(0.05)  # 약 20fps 주기로 프론트엔드 송출

    return StreamingResponse(
        frame_generator(), 
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


# API 2: 최신 전체 데이터 폴링 주소 (카메라별)
# 사용예: GET /api/control/latest?intersection_id=1&camera_id=1
@router.get("/latest")
def get_latest_traffic(intersection_id: int = Query(1), camera_id: int = Query(1)):
    key = (intersection_id, camera_id)
    state = camera_states.get(key)

    if not state or state.get("response") is None:
        return {
            "status": "WAITING", 
            "message": f"교차로 {intersection_id} - 카메라 {camera_id} AI 분석 데이터 대기 중"
        }

    return {
        "status": "ACTIVE",
        "intersection_id": intersection_id,
        "camera_id": camera_id,
        "data": state["data"],
        "result": state["response"]
    }


# API 3: SUMO 기존 bridge.py 호환 전용 신호 데이터 조회 주소
# 사용예: GET /api/control/signal?intersection_id=1
# app/routers/control.py 의 get_signal_status 엔드포인트

# app/routers/control.py 내부의 get_signal_status 엔드포인트 수정

@router.get("/signal")
def get_signal_status(intersection_id: int = Query(1)):
    # 해당 intersection_id를 가진 데이터 수색 (카메라 ID 우선순위 또는 통합 상태)
    target_state = None
    
    # 1. camera_states에서 요청된 intersection_id에 해당하는 최신 수신 데이터 찾기
    for key, state in camera_states.items():
        if key[0] == intersection_id and state.get("response") is not None:
            target_state = state
            break

    # 2. 해당 교차로 데이터가 없으면 타 교차로로 대체하지 않고 즉시 WAITING 반환
    if not target_state or target_state.get("response") is None:
        return {
            "status": "WAITING",
            "intersection_id": intersection_id,
            "message": f"교차로 {intersection_id}의 신호 제어 데이터 대기 중"
        }

    # 3. 방향별 차량 수 데이터 추출
    raw_data = target_state.get("data", {})
    vehicle_data = {
        "north_cars": raw_data.get("north_cars", 0),
        "south_cars": raw_data.get("south_cars", 0),
        "east_cars": raw_data.get("east_cars", 0),
        "west_cars": raw_data.get("west_cars", 0)
    }

    # 4. ACTIVE 응답 반환
    return {
        "status": "ACTIVE",
        "intersection_id": intersection_id,
        "data": vehicle_data,
        "result": target_state["response"]
    }