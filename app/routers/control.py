import base64
import asyncio
from typing import Dict, Tuple, List
from datetime import datetime
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from app.schemas.traffic import TrafficData, TrafficResponse
from app.services.logic import evaluate_traffic_control

router = APIRouter(prefix="/api/control", tags=["Control"])

# 카메라별 최신 전역 상태 저장소 (Key: (intersection_id, camera_id))
camera_states: Dict[Tuple[int, int], dict] = {}

# 돌발 사고 및 응급 차량 이벤트 이력 저장소 (최대 50개 유지)
event_logs: List[dict] = []


@router.post("/", response_model=TrafficResponse)
def control_traffic(data: TrafficData):
    # 1. 교차로 및 카메라 ID 추출
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

    # 3. 신호 제어 알고리즘 수행 (사고 / 응급차량 / ROI 대기차량 종합 평가)
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

    # 4. [신규] 돌발 사고 또는 응급차량 감지 시 타임스탬프 이력 저장
    if data.accident_detected or data.emergency_detected:
        event_type = "ACCIDENT" if data.accident_detected else "EMERGENCY"
        log_entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "intersection_id": intersection_id,
            "camera_id": camera_id,
            "event_type": event_type,
            "mode": result.get("mode"),
            "signal_action": result.get("signal_action"),
            "message": result.get("message"),
            "waiting_vehicles": data.vehicle_count
        }
        
        # 중복 로깅 방지 (최근 3초 내 동일 카메라 동일 이벤트가 아니면 저장)
        if not event_logs or event_logs[0]["camera_id"] != camera_id or event_logs[0]["event_type"] != event_type:
            event_logs.insert(0, log_entry)  # 최신순 삽입
            if len(event_logs) > 50:
                event_logs.pop()

    # 5. 최신 분석 데이터 및 신호 제어 결과 기록 (이미지 제외)
    dump_data = data.model_dump(exclude={"image_frame"}) if hasattr(data, "model_dump") else data.dict(exclude={"image_frame"})
    camera_states[key]["data"] = dump_data
    camera_states[key]["response"] = result

    return result


# ---------------------------------------------------------
# 프론트엔드, 관제 및 SUMO 연동 전용 API 엔드포인트
# ---------------------------------------------------------

# API 1: MJPEG 영상 스트리밍 주소 (카메라별)
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
            await asyncio.sleep(0.05)  # 약 20fps 주기로 전송

    return StreamingResponse(
        frame_generator(), 
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


# API 2: 최신 전체 데이터 폴링 주소 (카메라별)
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


# API 3: SUMO 제어 전용 신호 데이터 조회 주소
@router.get("/signal")
def get_signal_status(intersection_id: int = Query(1)):
    target_state = None
    
    for key, state in camera_states.items():
        if key[0] == intersection_id and state.get("response") is not None:
            target_state = state
            break

    if not target_state or target_state.get("response") is None:
        return {
            "status": "WAITING",
            "intersection_id": intersection_id,
            "message": f"교차로 {intersection_id}의 신호 제어 데이터 대기 중"
        }

    raw_data = target_state.get("data", {})
    vehicle_data = {
        "north_cars": raw_data.get("north_cars", 0),
        "south_cars": raw_data.get("south_cars", 0),
        "east_cars": raw_data.get("east_cars", 0),
        "west_cars": raw_data.get("west_cars", 0)
    }

    return {
        "status": "ACTIVE",
        "intersection_id": intersection_id,
        "data": vehicle_data,
        "result": target_state["response"]
    }


# API 4: [신규] 사고 및 응급차량 돌발 이벤트 이력 조회 API
@router.get("/events")
def get_event_logs():
    return {
        "total_events": len(event_logs),
        "events": event_logs
    }


# API 5: [신규] 교차로 실시간 통합 상황 집계 API
@router.get("/summary")
def get_intersection_summary(intersection_id: int = Query(1)):
    total_vehicles = 0
    has_accident = False
    has_emergency = False
    active_cams = []

    for (inter_id, cam_id), state in camera_states.items():
        if inter_id == intersection_id and state.get("data") is not None:
            cam_data = state["data"]
            total_vehicles += cam_data.get("vehicle_count", 0)
            if cam_data.get("accident_detected"):
                has_accident = True
            if cam_data.get("emergency_detected"):
                has_emergency = True
            active_cams.append(cam_id)

    status_str = "NORMAL"
    if has_emergency:
        status_str = "EMERGENCY_PRIORITY"
    elif has_accident:
        status_str = "ACCIDENT_LOCKDOWN"

    return {
        "intersection_id": intersection_id,
        "active_camera_count": len(active_cams),
        "total_waiting_vehicles": total_vehicles,
        "intersection_status": status_str,
        "has_accident": has_accident,
        "has_emergency": has_emergency
    }