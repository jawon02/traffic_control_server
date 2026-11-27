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

# 벤치마크/비교 측정용 배치 저장소 (Key: batch_id)
batches: Dict[str, dict] = {}
_batch_seq: int = 0

# 탐지 끊김(False)으로 중간에 풀리지 않게 유지하는 시간(초)
ACTIVE_GRACE_SECONDS = 8.0

# 응급 통과 완료(CLEARED) 상태를 유지할 시간(초)
CLEARED_HOLD_SECONDS = 5.0


def _generate_batch_id(intersection_id: int) -> str:
    global _batch_seq
    _batch_seq += 1
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"batch_i{intersection_id}_{ts}_{_batch_seq:04d}"


def _extract_vehicle_counts(source: dict) -> dict:
    keys = [
        "vehicle_count",
        "pedestrian_count",
        "exit_congested",
        "accident_detected",
        "north_cars",
        "north_left_cars",
        "north_straight_cars",
        "north_right_cars",
        "south_cars",
        "south_left_cars",
        "south_straight_cars",
        "south_right_cars",
        "east_cars",
        "east_left_cars",
        "east_straight_cars",
        "east_right_cars",
        "west_cars",
        "west_left_cars",
        "west_straight_cars",
        "west_right_cars",
    ]
    out = {}
    for k in keys:
        if k in source:
            out[k] = source[k]
        elif k in ("exit_congested", "accident_detected"):
            out[k] = False
        else:
            out[k] = 0
    return out


def _format_batch_summary(batch_record: dict) -> dict:
    counts = batch_record["counts"]
    return {
        "batch_id": batch_record["batch_id"],
        "intersection_id": batch_record["intersection_id"],
        "created_at": batch_record["created_at"],
        "direction_totals": {
            "north": counts.get("north_cars", 0),
            "east": counts.get("east_cars", 0),
            "south": counts.get("south_cars", 0),
            "west": counts.get("west_cars", 0),
        },
        "movement_counts": {
            "north": {
                "left": counts.get("north_left_cars", 0),
                "straight": counts.get("north_straight_cars", 0),
                "right": counts.get("north_right_cars", 0),
            },
            "east": {
                "left": counts.get("east_left_cars", 0),
                "straight": counts.get("east_straight_cars", 0),
                "right": counts.get("east_right_cars", 0),
            },
            "south": {
                "left": counts.get("south_left_cars", 0),
                "straight": counts.get("south_straight_cars", 0),
                "right": counts.get("south_right_cars", 0),
            },
            "west": {
                "left": counts.get("west_left_cars", 0),
                "straight": counts.get("west_straight_cars", 0),
                "right": counts.get("west_right_cars", 0),
            },
        },
        "raw_counts": deepcopy(counts),
    }


def _normalize_four_way_green_times(green_times: Optional[dict], default_sec: int = 30) -> dict:
    """east_green, west_green, north_green, south_green 키가 누락되지 않도록 보정합니다."""
    src = green_times or {}
    ns_fallback = src.get("north_south_green", default_sec)
    ew_fallback = src.get("east_west_green", default_sec)

    normalized = dict(src)
    normalized["east_green"] = src.get("east_green", ew_fallback)
    normalized["west_green"] = src.get("west_green", ew_fallback)
    normalized["north_green"] = src.get("north_green", ns_fallback)
    normalized["south_green"] = src.get("south_green", ns_fallback)
    return normalized


def _get_or_init_emergency_state(intersection_id: int) -> dict:
    if intersection_id not in emergency_states:
        emergency_states[intersection_id] = {
            "event_state": "NONE",
            "priority_direction": None,
            "emergency_vehicle_id": None,
            "last_seen_active_ts": None,
            "cleared_at": None,
            "paused_signal": None,
            "consumed_ids": set(),
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
        "green_times": _normalize_four_way_green_times(base["green_times"]),
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
    merged_data = _extract_vehicle_counts({})
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


def _build_profile_result(
    counts: dict,
    profile: str,
    batch_id: Optional[str] = None,
    emergency_detected: bool = False,
    emergency_vehicle_id: Optional[str] = None,
    priority_direction: Optional[str] = None,
) -> dict:
    normalized_profile = (profile or "adaptive").lower()

    if normalized_profile == "baseline":
        green_times = _normalize_four_way_green_times(
            _make_green_times(30, 30, 30, 30),
            default_sec=30,
        )
        res = {
            "mode": "BASELINE_FIXED",
            "signal_action": "FIXED_30S_CYCLE",
            "event_state": "NONE",
            "priority_direction": None,
            "emergency_vehicle_id": None,
            "active_events": [],
            "green_times": green_times,
            "signal_state": _build_signal_state("HOLD_CURRENT_SIGNAL"),
            "message": "기준 신호(BASELINE) 적용: 동·서·남·북 각 30초 고정 신호 주기입니다.",
            "profile": "baseline",
        }
        if batch_id is not None:
            res["batch_id"] = batch_id
        return res

    res = evaluate_traffic_control(
        pedestrian_count=counts.get("pedestrian_count", 0),
        exit_congested=bool(counts.get("exit_congested", False)),
        accident_detected=bool(counts.get("accident_detected", False)),
        emergency_detected=emergency_detected,
        north_cars=counts.get("north_cars", 0),
        south_cars=counts.get("south_cars", 0),
        east_cars=counts.get("east_cars", 0),
        west_cars=counts.get("west_cars", 0),
        emergency_vehicle_id=emergency_vehicle_id,
        priority_direction=priority_direction,
    )
    res["green_times"] = _normalize_four_way_green_times(res.get("green_times"), default_sec=30)
    res["profile"] = "adaptive"
    if batch_id is not None:
        res["batch_id"] = batch_id
    return res


@router.post("/")
def control_traffic(
    data: TrafficData,
    batch_id: Optional[str] = Query(default=None),
):
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

    resolved_batch_id = batch_id or dump_data.get("batch_id") or _generate_batch_id(intersection_id)
    batch_counts = _extract_vehicle_counts(dump_data)
    if resolved_batch_id not in batches:
        batches[resolved_batch_id] = {
            "batch_id": resolved_batch_id,
            "intersection_id": intersection_id,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "counts": batch_counts,
        }
    else:
        existing_counts = batches[resolved_batch_id]["counts"]
        if camera_id == 1:
            for k in (
                "north_cars",
                "north_left_cars",
                "north_straight_cars",
                "north_right_cars",
                "south_cars",
                "south_left_cars",
                "south_straight_cars",
                "south_right_cars",
                "east_cars",
                "east_left_cars",
                "east_straight_cars",
                "east_right_cars",
                "west_cars",
                "west_left_cars",
                "west_straight_cars",
                "west_right_cars",
                "vehicle_count",
            ):
                existing_counts[k] = batch_counts.get(k, 0)
        existing_counts["pedestrian_count"] = max(
            existing_counts.get("pedestrian_count", 0),
            batch_counts.get("pedestrian_count", 0),
        )
        existing_counts["exit_congested"] = bool(
            existing_counts.get("exit_congested", False) or batch_counts.get("exit_congested", False)
        )
        existing_counts["accident_detected"] = bool(
            existing_counts.get("accident_detected", False) or batch_counts.get("accident_detected", False)
        )

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
    result["green_times"] = _normalize_four_way_green_times(result.get("green_times"), default_sec=30)

    if emg_state["event_state"] == "CLEARED":
        paused = emg_state.get("paused_signal") or paused_snapshot
        result["mode"] = paused["mode"]
        result["signal_action"] = paused["signal_action"]
        result["green_times"] = _normalize_four_way_green_times(paused["green_times"], default_sec=30)
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

    result["batch_id"] = resolved_batch_id
    camera_states[key]["response"] = result
    return result


@router.get("/batch/{batch_id}")
def get_batch_info(batch_id: str):
    """특정 batch_id의 방향별 총 차량 수와 회전별 차량 수를 조회합니다."""
    batch_record = batches.get(batch_id)
    if not batch_record:
        return {
            "status": "WAITING",
            "batch_id": batch_id,
            "message": f"배치 {batch_id} 데이터를 찾을 수 없습니다.",
        }
    return {
        "status": "ACTIVE",
        **_format_batch_summary(batch_record),
    }


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
        "restored_green_times": _normalize_four_way_green_times(paused.get("green_times"), default_sec=30),
    }


@router.post("/emergency/reset")
def reset_emergency_history(
    intersection_id: int = Query(1),
    clear_batches: bool = Query(False),
):
    """재테스트를 원할 때 완료된 응급 ID 기록과 상태를 초기화합니다."""
    state = _get_or_init_emergency_state(intersection_id)
    state["consumed_ids"].clear()
    state["event_state"] = "NONE"
    state["priority_direction"] = None
    state["emergency_vehicle_id"] = None
    state["last_seen_active_ts"] = None
    state["cleared_at"] = None
    state["paused_signal"] = None

    if clear_batches:
        to_del = [bid for bid, b in batches.items() if b.get("intersection_id") == intersection_id]
        for bid in to_del:
            del batches[bid]

    return {
        "status": "OK",
        "intersection_id": intersection_id,
        "cleared_batches": clear_batches,
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
            "batch_id": None,
            "message": f"교차로 {intersection_id} - 카메라 {camera_id} AI 분석 데이터 대기 중",
        }

    resp = state["response"]
    return {
        "status": "ACTIVE",
        "intersection_id": intersection_id,
        "camera_id": camera_id,
        "batch_id": resp.get("batch_id"),
        "data": state["data"],
        "result": resp,
    }


@router.get("/signal")
def get_signal_status(
    intersection_id: int = Query(1),
    batch_id: Optional[str] = Query(default=None),
    profile: Optional[str] = Query(default=None),
):
    if batch_id is not None:
        batch_record = batches.get(batch_id)
        if not batch_record:
            default_gt = _normalize_four_way_green_times(_make_green_times(30, 30, 30, 30), default_sec=30)
            return {
                "status": "WAITING",
                "intersection_id": intersection_id,
                "batch_id": batch_id,
                "profile": profile or "adaptive",
                "message": f"배치 {batch_id} 데이터가 아직 준비되지 않았습니다.",
                "data": None,
                "result": {
                    "mode": "WAITING",
                    "signal_action": "WAIT",
                    "event_state": "NONE",
                    "priority_direction": None,
                    "emergency_vehicle_id": None,
                    "active_events": [],
                    "batch_id": batch_id,
                    "profile": profile or "adaptive",
                    "message": f"배치 {batch_id} 데이터가 아직 준비되지 않았습니다.",
                    "green_times": default_gt,
                    "signal_state": _build_signal_state("HOLD_CURRENT_SIGNAL"),
                },
            }

        counts = batch_record["counts"]
        chosen_profile = profile or "adaptive"
        control_result = _build_profile_result(
            counts=counts,
            profile=chosen_profile,
            batch_id=batch_id,
        )
        return {
            "status": "ACTIVE",
            "intersection_id": intersection_id,
            "batch_id": batch_id,
            "profile": chosen_profile,
            "data": counts,
            "batch_summary": _format_batch_summary(batch_record),
            "result": control_result,
        }

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
    base_result["green_times"] = _normalize_four_way_green_times(base_result.get("green_times"), default_sec=30)

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
                "green_times": _normalize_four_way_green_times(_make_green_times(30, 30, 30, 30), default_sec=30),
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
            "green_times": _normalize_four_way_green_times(_make_green_times(30, 30, 30, 30), default_sec=30),
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
            "green_times": _normalize_four_way_green_times(paused["green_times"], default_sec=30),
            "signal_state": deepcopy(paused["signal_state"]),
        }
        return {
            "status": "ACTIVE",
            "intersection_id": intersection_id,
            "data": merged_data,
            "result": cleared_result,
        }

    if profile and profile.lower() == "baseline":
        baseline_res = _build_profile_result(merged_data, profile="baseline")
        return {
            "status": "ACTIVE",
            "intersection_id": intersection_id,
            "profile": "baseline",
            "data": merged_data,
            "result": baseline_res,
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