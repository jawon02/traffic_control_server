import asyncio
import base64
from copy import deepcopy
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

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

# 교차로별 응급 이벤트 상태 머신 및 일시정지된 직전 신호 저장소 (Key: intersection_id)
# event_state: "NONE" | "ACTIVE" | "CLEARED"
emergency_states: Dict[int, dict] = {}

# 돌발 사고 및 응급 차량 이벤트 이력 저장소 (최대 50개 유지)
event_logs: List[dict] = []

# 탐지 끊김(False)으로 중간에 풀리지 않게 유지하는 시간(초)
ACTIVE_GRACE_SECONDS = 8.0

# 응급 통과 완료(CLEARED) 상태를 유지할 시간(초)
CLEARED_HOLD_SECONDS = 5.0


def _get_or_init_emergency_state(intersection_id: int) -> dict:
    if intersection_id not in emergency_states:
        emergency_states[intersection_id] = {
            "event_state": "NONE",
            "priority_direction": None,
            "emergency_vehicle_id": None,
            "last_seen_active_ts": None,
            "cleared_at": None,
            "paused_signal": None,
            "consumed_ids": set(),  # 1회용 처리: 이미 완료된 응급차량 ID 기록
        }
    return emergency_states[intersection_id]


def _snapshot_normal_or_congestion_signal(merged_data: dict) -> dict:
    """응급 진입 시점 기준 일반/혼잡 신호 제어 상태를 스냅샷으로 고정합니다."""
    base = evaluate_base_traffic(
        pedestrian_count=0,
        exit_congested=False,
        accident_detected=False,
        north_cars=merged_data.get("north_cars", 0),
        south_cars=merged_data.get("south_cars", 0),
        east_cars=merged_data.get("east_cars", 0),
        west_cars=merged_data.get("west_cars", 0),
    )
    return {
        "mode": base["mode"],
        "signal_action": base["signal_action"],
        "green_times": deepcopy(base["green_times"]),
        "signal_state": deepcopy(base["signal_state"]),
        "message": base["message"],
    }


def _update_emergency_state(
    intersection_id: int,
    emergency_detected: bool,
    now_ts: float,
    paused_candidate: Optional[dict] = None,
    vehicle_id: Optional[str] = None,
    direction: Optional[str] = None,
) -> dict:
    state = _get_or_init_emergency_state(intersection_id)
    consumed_ids: Set[str] = state["consumed_ids"]
    candidate_id = vehicle_id or DEFAULT_EMERGENCY_VEHICLE_ID
    resolved_dir = (direction or state.get("priority_direction") or DEFAULT_EMERGENCY_DIRECTION).upper()

    if emergency_detected:
        # 이미 1회 처리 완료된 응급차량 ID면 영상 루프로 True가 다시 와도 ACTIVE로 재진입하지 않음
        if state["event_state"] != "ACTIVE" and candidate_id in consumed_ids:
            pass
        else:
            if state["event_state"] != "ACTIVE":
                state["paused_signal"] = (
                    deepcopy(paused_candidate) if paused_candidate is not None else None
                )
            state["event_state"] = "ACTIVE"
            state["priority_direction"] = resolved_dir
            state["emergency_vehicle_id"] = candidate_id
            state["last_seen_active_ts"] = now_ts
            state["cleared_at"] = None
            return state

    # emergency_detected가 False이거나 이미 소비된 ID로 루프가 도는 경우
    if state["event_state"] == "ACTIVE":
        last_seen = state.get("last_seen_active_ts")
        if last_seen is None or (now_ts - last_seen) >= ACTIVE_GRACE_SECONDS:
            if state.get("emergency_vehicle_id"):
                consumed_ids.add(state["emergency_vehicle_id"])
            state["event_state"] = "CLEARED"
            state["priority_direction"] = None
            state["emergency_vehicle_id"] = None
            state["last_seen_active_ts"] = None
            state["cleared_at"] = now_ts
    elif state["event_state"] == "CLEARED":
        cleared_at = state.get("cleared_at")
        if cleared_at is not None and (now_ts - cleared_at) > CLEARED_HOLD_SECONDS:
            state["event_state"] = "NONE"
            state["cleared_at"] = None
            state["paused_signal"] = None

    return state


def mark_emergency_cleared(intersection_id: int) -> dict:
    """SUMO 브리지에서 응급차량이 교차로를 통과한 시점에 즉시 CLEARED로 전환하고 1회용 완료 처리합니다."""
    now_ts = datetime.now().timestamp()
    state = _get_or_init_emergency_state(intersection_id)
    if state.get("emergency_vehicle_id"):
        state["consumed_ids"].add(state["emergency_vehicle_id"])
    else:
        state["consumed_ids"].add(DEFAULT_EMERGENCY_VEHICLE_ID)

    if state.get("paused_signal") is None:
        merged_data, _, _ = _aggregate_intersection_data(intersection_id)
        state["paused_signal"] = _snapshot_normal_or_congestion_signal(merged_data)

    state["event_state"] = "CLEARED"
    state["priority_direction"] = None
    state["emergency_vehicle_id"] = None
    state["last_seen_active_ts"] = None
    state["cleared_at"] = now_ts
    return state


def _aggregate_intersection_data(intersection_id: int) -> Tuple[dict, bool, bool]:
    """교차로(intersection_id)에 속한 카메라 데이터를 병합합니다."""
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

    merged_data, _, emergency_from_cam = _aggregate_intersection_data(intersection_id)
    paused_snapshot = _snapshot_normal_or_congestion_signal(merged_data)

    if camera_id == 3 or data.emergency_detected or emergency_from_cam:
        _update_emergency_state(
            intersection_id=intersection_id,
            emergency_detected=bool(data.emergency_detected or emergency_from_cam),
            now_ts=now_ts,
            paused_candidate=paused_snapshot,
            vehicle_id=DEFAULT_EMERGENCY_VEHICLE_ID if (data.emergency_detected or emergency_from_cam) else None,
            direction=DEFAULT_EMERGENCY_DIRECTION if (data.emergency_detected or emergency_from_cam) else None,
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
        paused = emg_state.get("paused_signal") or paused_snapshot
        result["mode"] = paused["mode"]
        result["signal_action"] = paused["signal_action"]
        result["green_times"] = deepcopy(paused["green_times"])
        result["signal_state"] = deepcopy(paused["signal_state"])
        result["event_state"] = "CLEARED"
        result["priority_direction"] = None
        result["emergency_vehicle_id"] = None
        result["active_events"] = []

    if data.accident_detected or is_emg_active:
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


@router.post("/emergency/clear")
def clear_emergency_event(intersection_id: int = Query(1)):
    """SUMO 브리지에서 응급차량이 교차로를 통과한 시점에 호출하는 해제 엔드포인트."""
    state = mark_emergency_cleared(intersection_id)
    paused = state.get("paused_signal") or {}
    return {
        "status": "OK",
        "intersection_id": intersection_id,
        "event_state": state["event_state"],
        "restored_mode": paused.get("mode"),
        "restored_green_times": paused.get("green_times"),
    }


@router.post("/emergency/reset")
def reset_emergency_history(intersection_id: int = Query(1)):
    """재테스트를 원할 때 완료된 응급 ID 기록을 초기화합니다."""
    state = _get_or_init_emergency_state(intersection_id)
    state["consumed_ids"].clear()
    state["event_state"] = "NONE"
    state["priority_direction"] = None
    state["emergency_vehicle_id"] = None
    state["last_seen_active_ts"] = None
    state["cleared_at"] = None
    state["paused_signal"] = None
    return {
        "status": "OK",
        "intersection_id": intersection_id,
        "message": "응급 이벤트 이력 및 상태가 초기화되었습니다.",
    }


# ---------------------------------------------------------
# 프론트엔드, 관제 및 SUMO 연동 전용 API 엔드포인트
# ---------------------------------------------------------

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


@router.get("/signal")
def get_signal_status(intersection_id: int = Query(1)):
    now_ts = datetime.now().timestamp()
    merged_data, has_any_data, emergency_from_cam = _aggregate_intersection_data(intersection_id)
    paused_snapshot = _snapshot_normal_or_congestion_signal(merged_data)
    base_result = evaluate_base_traffic(
        pedestrian_count=merged_data.get("pedestrian_count", 0),
        exit_congested=bool(merged_data.get("exit_congested", False)),
        accident_detected=bool(merged_data.get("accident_detected", False)),
        north_cars=merged_data.get("north_cars", 0),
        south_cars=merged_data.get("south_cars", 0),
        east_cars=merged_data.get("east_cars", 0),
        west_cars=merged_data.get("west_cars", 0),
    )

    emg_state = _update_emergency_state(
        intersection_id=intersection_id,
        emergency_detected=emergency_from_cam,
        now_ts=now_ts,
        paused_candidate=paused_snapshot,
    )

    event_state = emg_state["event_state"]

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
            "message": f"[긴급] 응급 차량 접근 감지! {direction} 방향 골든타임 확보를 위해 즉시 우선 신호를 부여합니다.",
            "green_times": _make_green_times(30, 30, 30, 30),
            "signal_state": _build_signal_state("EMERGENCY_CORRIDOR_GREEN", priority_direction=direction),
        }
        return {
            "status": "ACTIVE",
            "intersection_id": intersection_id,
            "data": merged_data,
            "result": control_result,
        }

    if event_state == "CLEARED":
        paused = emg_state.get("paused_signal") or paused_snapshot
        cleared_result = {
            "mode": paused["mode"],
            "signal_action": paused["signal_action"],
            "event_state": "CLEARED",
            "priority_direction": None,
            "emergency_vehicle_id": None,
            "active_events": [],
            "message": f"응급 차량 통과 완료. 일시정지되었던 {paused['mode']} 신호 제어를 재개합니다.",
            "green_times": deepcopy(paused["green_times"]),
            "signal_state": deepcopy(paused["signal_state"]),
        }
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


@router.get("/events")
def get_event_logs():
    return {
        "total_events": len(event_logs),
        "events": event_logs,
    }


@router.get("/summary")
def get_intersection_summary(intersection_id: int = Query(1)):
    total_vehicles = 0
    has_accident = False
    active_cams = []
    emg_state = _get_or_init_emergency_state(intersection_id)
    has_emergency = emg_state.get("event_state") == "ACTIVE"

    for (inter_id, cam_id), state in camera_states.items():
        if inter_id == intersection_id and state.get("data") is not None:
            cam_data = state["data"]
            total_vehicles += cam_data.get("vehicle_count", 0)
            if cam_data.get("accident_detected"):
                has_accident = True
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