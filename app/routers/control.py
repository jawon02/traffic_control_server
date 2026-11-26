import asyncio
import base64
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.schemas.traffic import TrafficData, TrafficResponse
from app.services.logic import (
    DEFAULT_EMERGENCY_DIRECTION,
    DEFAULT_EMERGENCY_VEHICLE_ID,
    _build_signal_state,
    _make_green_times,
    evaluate_base_traffic,
    evaluate_traffic_control,
)

router = APIRouter(prefix="/api/control", tags=["Control"])

# 카메라별 최신 전역 상태 저장소 (Key: (intersection_id, camera_id))
camera_states: Dict[Tuple[int, int], dict] = {}

# 교차로별 응급 이벤트 상태 머신 저장소 (Key: intersection_id)
# event_state: "NONE" | "ACTIVE" | "CLEARED"
emergency_states: Dict[int, dict] = {}

# 돌발 사고 및 응급 차량 이벤트 이력 저장소 (최대 50개 유지)
event_logs: List[dict] = []

# 응급 통과 완료(CLEARED) 상태를 유지할 시간(초)
CLEARED_HOLD_SECONDS = 5.0


def _get_or_init_emergency_state(intersection_id: int) -> dict:
    if intersection_id not in emergency_states:
        emergency_states[intersection_id] = {
            "event_state": "NONE",
            "priority_direction": None,
            "emergency_vehicle_id": None,
            "cleared_at": None,
        }
    return emergency_states[intersection_id]


def _update_emergency_state(
    intersection_id: int,
    emergency_detected: bool,
    now_ts: float,
    vehicle_id: Optional[str] = None,
    direction: Optional[str] = None,
) -> dict:
    state = _get_or_init_emergency_state(intersection_id)
    resolved_id = vehicle_id or state.get("emergency_vehicle_id") or DEFAULT_EMERGENCY_VEHICLE_ID
    resolved_dir = (direction or state.get("priority_direction") or DEFAULT_EMERGENCY_DIRECTION).upper()

    if emergency_detected:
        state["event_state"] = "ACTIVE"
        state["priority_direction"] = resolved_dir
        state["emergency_vehicle_id"] = resolved_id
        state["cleared_at"] = None
    else:
        if state["event_state"] == "ACTIVE":
            state["event_state"] = "CLEARED"
            state["priority_direction"] = None
            state["emergency_vehicle_id"] = None
            state["cleared_at"] = now_ts
        elif state["event_state"] == "CLEARED":
            cleared_at = state.get("cleared_at")
            if cleared_at is not None and (now_ts - cleared_at) > CLEARED_HOLD_SECONDS:
                state["event_state"] = "NONE"
                state["cleared_at"] = None

    return state


def _aggregate_intersection_data(intersection_id: int) -> Tuple[dict, bool, bool]:
    """교차로(intersection_id)에 속한 카메라 데이터를 병합합니다.

    - 카메라 1번(혼잡)의 방향/회전 차량 수 및 혼잡/사고/보행자 지표를 기준으로 집계
    - 카메라 3번(응급차량)의 emergency_detected 상태를 별도 반영
    """
    merged_data = {
        "vehicle_count": 0,
        "pedestrian_count": 0,
        "exit_congested": False,
        "accident_detected": False,
        "north_cars": 0,
        "north_left_cars": 0,
        "north_straight_cars": 0,
        "north_right_cars": 0,
        "south_cars": 0,
        "south_left_cars": 0,
        "south_straight_cars": 0,
        "south_right_cars": 0,
        "east_cars": 0,
        "east_left_cars": 0,
        "east_straight_cars": 0,
        "east_right_cars": 0,
        "west_cars": 0,
        "west_left_cars": 0,
        "west_straight_cars": 0,
        "west_right_cars": 0,
    }

    has_any_data = False
    emergency_active_from_cam = False

    cam1_state = camera_states.get((intersection_id, 1))
    if cam1_state and cam1_state.get("data") is not None:
        has_any_data = True
        cam1_data = cam1_state["data"]
        for k in merged_data:
            if k in cam1_data:
                merged_data[k] = cam1_data[k]
        if cam1_data.get("emergency_detected"):
            emergency_active_from_cam = True

    for (inter_id, cam_id), state in camera_states.items():
        if inter_id != intersection_id or state.get("data") is None:
            continue
        has_any_data = True
        cam_data = state["data"]
        if cam_data.get("emergency_detected"):
            emergency_active_from_cam = True
        if cam_id != 1:
            if cam_data.get("accident_detected"):
                merged_data["accident_detected"] = True
            if cam_data.get("exit_congested"):
                merged_data["exit_congested"] = True
            merged_data["pedestrian_count"] = max(
                merged_data["pedestrian_count"],
                cam_data.get("pedestrian_count", 0),
            )

    return merged_data, has_any_data, emergency_active_from_cam


@router.post("/", response_model=TrafficResponse)
def control_traffic(data: TrafficData):
    intersection_id = getattr(data, "intersection_id", 1)
    camera_id = getattr(data, "camera_id", 1)
    key = (intersection_id, camera_id)
    now_ts = datetime.now().timestamp()

    if key not in camera_states:
        camera_states[key] = {
            "frame_bytes": None,
            "response": None,
            "data": None,
        }

    if data.image_frame:
        try:
            camera_states[key]["frame_bytes"] = base64.b64decode(data.image_frame)
        except Exception as e:
            print(f"[ERROR] Frame decode failed (intersection {intersection_id}, cam {camera_id}): {e}")

    dump_data = (
        data.model_dump(exclude={"image_frame"})
        if hasattr(data, "model_dump")
        else data.dict(exclude={"image_frame"})
    )
    camera_states[key]["data"] = dump_data

    # 카메라 3번(또는 응급 감지 카메라) 기준 응급 상태 머신 갱신
    if camera_id == 3 or data.emergency_detected:
        _update_emergency_state(
            intersection_id=intersection_id,
            emergency_detected=bool(data.emergency_detected),
            now_ts=now_ts,
            vehicle_id=DEFAULT_EMERGENCY_VEHICLE_ID if data.emergency_detected else None,
            direction=DEFAULT_EMERGENCY_DIRECTION if data.emergency_detected else None,
        )

    emg_state = _get_or_init_emergency_state(intersection_id)
    is_emg_active = emg_state["event_state"] == "ACTIVE"

    result = evaluate_traffic_control(
        pedestrian_count=data.pedestrian_count,
        exit_congested=data.exit_congested,
        accident_detected=data.accident_detected,
        emergency_detected=is_emg_active,
        north_cars=data.north_cars,
        south_cars=data.south_cars,
        east_cars=data.east_cars,
        west_cars=data.west_cars,
        emergency_vehicle_id=emg_state.get("emergency_vehicle_id"),
        priority_direction=emg_state.get("priority_direction"),
    )

    if emg_state["event_state"] == "CLEARED":
        result["event_state"] = "CLEARED"
        result["priority_direction"] = None
        result["emergency_vehicle_id"] = None
        result["active_events"] = []

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
            "waiting_vehicles": data.vehicle_count,
        }
        if not event_logs or event_logs[0]["camera_id"] != camera_id or event_logs[0]["event_type"] != event_type:
            event_logs.insert(0, log_entry)
            if len(event_logs) > 50:
                event_logs.pop()

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
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + state["frame_bytes"] + b"\r\n"
                )
            await asyncio.sleep(0.05)

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# API 2: 최신 전체 데이터 폴링 주소 (카메라별)
@router.get("/latest")
def get_latest_traffic(intersection_id: int = Query(1), camera_id: int = Query(1)):
    key = (intersection_id, camera_id)
    state = camera_states.get(key)

    if not state or state.get("response") is None:
        return {
            "status": "WAITING",
            "message": f"교차로 {intersection_id} - 카메라 {camera_id} AI 분석 데이터 대기 중",
        }

    return {
        "status": "ACTIVE",
        "intersection_id": intersection_id,
        "camera_id": camera_id,
        "data": state["data"],
        "result": state["response"],
    }


# API 3: SUMO 제어 전용 신호 데이터 조회 주소
@router.get("/signal")
def get_signal_status(intersection_id: int = Query(1)):
    now_ts = datetime.now().timestamp()
    merged_data, has_any_data, emergency_from_cam = _aggregate_intersection_data(intersection_id)
    emg_state = _update_emergency_state(
        intersection_id=intersection_id,
        emergency_detected=emergency_from_cam,
        now_ts=now_ts,
    )

    event_state = emg_state["event_state"]

    # 응급 이벤트가 ACTIVE 또는 CLEARED 상태일 때는 WAITING으로 떨어지지 않고 상태 유지
    if not has_any_data and event_state == "NONE":
        return {
            "status": "WAITING",
            "intersection_id": intersection_id,
            "message": f"교차로 {intersection_id}의 신호 제어 데이터 대기 중",
            "data": merged_data,
            "result": {
                "mode": "WAITING",
                "signal_action": "WAIT",
                "event_state": "NONE",
                "priority_direction": None,
                "emergency_vehicle_id": None,
                "active_events": [],
                "message": f"교차로 {intersection_id}의 신호 제어 데이터 대기 중",
                "green_times": _make_green_times(30, 30, 30, 30),
                "signal_state": _build_signal_state("HOLD_CURRENT_SIGNAL"),
            },
        }

    base_result = evaluate_base_traffic(
        pedestrian_count=merged_data.get("pedestrian_count", 0),
        exit_congested=bool(merged_data.get("exit_congested", False)),
        accident_detected=bool(merged_data.get("accident_detected", False)),
        north_cars=merged_data.get("north_cars", 0),
        south_cars=merged_data.get("south_cars", 0),
        east_cars=merged_data.get("east_cars", 0),
        west_cars=merged_data.get("west_cars", 0),
    )

    if event_state == "ACTIVE":
        vehicle_id = emg_state.get("emergency_vehicle_id") or DEFAULT_EMERGENCY_VEHICLE_ID
        direction = (emg_state.get("priority_direction") or DEFAULT_EMERGENCY_DIRECTION).upper()
        active_events_payload = [
            {
                "type": "EMERGENCY",
                "direction": direction,
                "vehicle_id": vehicle_id,
            }
        ]
        control_result = {
            "mode": "EMERGENCY_VEHICLE_PRIORITY",
            "signal_action": "EMERGENCY_CORRIDOR_GREEN",
            "event_state": "ACTIVE",
            "priority_direction": direction,
            "emergency_vehicle_id": vehicle_id,
            "active_events": active_events_payload,
            "message": "[긴급] 응급 차량 접근 감지! 동쪽 방향 우선 신호를 연동합니다.",
            "green_times": _make_green_times(30, 30, 30, 30),
            "signal_state": _build_signal_state("EMERGENCY_CORRIDOR_GREEN"),
        }
        return {
            "status": "ACTIVE",
            "intersection_id": intersection_id,
            "data": merged_data,
            "result": control_result,
        }

    if event_state == "CLEARED":
        cleared_result = dict(base_result)
        cleared_result["event_state"] = "CLEARED"
        cleared_result["priority_direction"] = None
        cleared_result["emergency_vehicle_id"] = None
        cleared_result["active_events"] = []
        return {
            "status": "ACTIVE",
            "intersection_id": intersection_id,
            "data": merged_data,
            "result": cleared_result,
        }

    return {
        "status": "ACTIVE",
        "intersection_id": intersection_id,
        "data": merged_data,
        "result": base_result,
    }


# API 4: 사고 및 응급차량 돌발 이벤트 이력 조회 API
@router.get("/events")
def get_event_logs():
    return {
        "total_events": len(event_logs),
        "events": event_logs,
    }


# API 5: 교차로 실시간 통합 상황 집계 API
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
        "has_emergency": has_emergency,
    }