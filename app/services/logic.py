from typing import Dict, Any, List, Optional

# 이벤트별 우선순위 가중치 (Scoring Matrix)
EVENT_WEIGHTS = {
    "EMERGENCY_VEHICLE": 100,  # 최우선 (골든타임 확보)
    "ACCIDENT": 80,            # 2차 사고 방지
    "EXIT_CONGESTED": 40,      # 교차로 꼬리물기 차단
    "HEAVY_PEDESTRIAN": 20,    # 보행자 안전
}

DEFAULT_EMERGENCY_VEHICLE_ID = "EMG-CAM3-001"
DEFAULT_EMERGENCY_DIRECTION = "EAST"


def _make_green_times(
    east_green: int,
    north_green: int,
    south_green: int,
    west_green: int,
) -> Dict[str, int]:
    return {
        "east_green": east_green,
        "north_green": north_green,
        "south_green": south_green,
        "west_green": west_green,
    }


def _build_signal_state(action: str) -> Dict[str, str]:
    """신호 제어 액션에 따라 4방향(N/S/E/W) 개별 신호 상태를 동적으로 생성합니다."""
    if action == "EMERGENCY_CORRIDOR_GREEN":
        return {"north": "RED", "south": "RED", "east": "GREEN", "west": "RED"}
    elif action == "ACCIDENT_LANE_RED":
        return {"north": "RED", "south": "RED", "east": "YELLOW", "west": "YELLOW"}
    elif action == "ALL_RED_EXCEPT_BYPASS":
        return {"north": "RED", "south": "RED", "east": "RED", "west": "RED"}
    elif action == "HOLD_CURRENT_SIGNAL":
        return {"north": "RED", "south": "RED", "east": "RED", "west": "RED"}
    elif action == "EXTEND_NORTH_SOUTH_GREEN":
        return {"north": "GREEN", "south": "GREEN", "east": "RED", "west": "RED"}
    elif action == "EXTEND_EAST_WEST_GREEN":
        return {"north": "RED", "south": "RED", "east": "GREEN", "west": "GREEN"}
    else:
        return {"north": "GREEN", "south": "GREEN", "east": "RED", "west": "RED"}


def evaluate_base_traffic(
    pedestrian_count: int,
    exit_congested: bool,
    accident_detected: bool,
    north_cars: int,
    south_cars: int,
    east_cars: int = 0,
    west_cars: int = 0,
) -> Dict[str, Any]:
    """응급차량 외 일반/혼잡/사고/보행자 기준의 기본 신호 제어 결과를 계산합니다."""
    active_event_names: List[str] = []
    total_risk_score = 0

    if accident_detected:
        active_event_names.append("ACCIDENT")
        total_risk_score += EVENT_WEIGHTS["ACCIDENT"]
    if exit_congested:
        active_event_names.append("EXIT_CONGESTED")
        total_risk_score += EVENT_WEIGHTS["EXIT_CONGESTED"]
    if pedestrian_count > 5:
        active_event_names.append("HEAVY_PEDESTRIAN")
        total_risk_score += EVENT_WEIGHTS["HEAVY_PEDESTRIAN"]

    if accident_detected:
        action = "ACCIDENT_LANE_RED" if len(active_event_names) == 1 else "ALL_RED_EXCEPT_BYPASS"
        mode = "SINGLE_ACCIDENT_LOCKDOWN" if len(active_event_names) == 1 else "COMPLEX_ACCIDENT_CONTROL"
        return {
            "mode": mode,
            "signal_action": action,
            "event_state": "NONE",
            "priority_direction": None,
            "emergency_vehicle_id": None,
            "active_events": [{"type": name} for name in active_event_names],
            "message": "[위험] 돌발 사고 감지! 2차 추돌 방지를 위해 진입 신호를 제어합니다.",
            "green_times": _make_green_times(10, 10, 10, 10),
            "signal_state": _build_signal_state(action),
        }

    if exit_congested:
        action = "HOLD_CURRENT_SIGNAL"
        mode = "EXIT_BLOCKED_PROTECTION" if len(active_event_names) == 1 else "COMPLEX_CONGESTION_CONTROL"
        return {
            "mode": mode,
            "signal_action": action,
            "event_state": "NONE",
            "priority_direction": None,
            "emergency_vehicle_id": None,
            "active_events": [{"type": name} for name in active_event_names],
            "message": "[경고] 출구 방향 정체 심각: 교차로 내 꼬리물기 차단을 위해 진행 신호를 일시 보류합니다.",
            "green_times": _make_green_times(15, 15, 15, 15),
            "signal_state": _build_signal_state(action),
        }

    if pedestrian_count > 5:
        action = "EXTEND_NORTH_SOUTH_GREEN"
        return {
            "mode": "PEDESTRIAN_PROTECTION",
            "signal_action": "PEDESTRIAN_GREEN_EXTENDED",
            "event_state": "NONE",
            "priority_direction": None,
            "emergency_vehicle_id": None,
            "active_events": [{"type": "HEAVY_PEDESTRIAN"}],
            "message": "[주의] 보행자 밀집 감지: 보행자 안전 확보를 위해 횡단 신호를 연장합니다.",
            "green_times": _make_green_times(15, 25, 25, 15),
            "signal_state": _build_signal_state(action),
        }

    ns_total = north_cars + south_cars
    ew_total = east_cars + west_cars

    if ns_total >= ew_total * 1.5 and ns_total > 5:
        mode = "CONGESTION_PATTERN"
        action = "EXTEND_NORTH_SOUTH_GREEN"
        east_g, north_g, south_g, west_g = 15, 40, 40, 15
        msg_detail = f"남북 대기열 정체 (남북:{ns_total}대 vs 동서:{ew_total}대). 남북 녹색 시간 연장."
    elif ew_total >= ns_total * 1.5 and ew_total > 5:
        mode = "CONGESTION_PATTERN"
        action = "EXTEND_EAST_WEST_GREEN"
        east_g, north_g, south_g, west_g = 40, 15, 15, 40
        msg_detail = f"동서 대기열 정체 (동서:{ew_total}대 vs 남북:{ns_total}대). 동서 녹색 시간 연장."
    else:
        mode = "NORMAL_PATTERN"
        action = "REGULAR_CYCLE"
        east_g, north_g, south_g, west_g = 30, 30, 30, 30
        msg_detail = f"정상 교통 흐름 (남북:{ns_total}대, 동서:{ew_total}대)."

    return {
        "mode": mode,
        "signal_action": action,
        "event_state": "NONE",
        "priority_direction": None,
        "emergency_vehicle_id": None,
        "active_events": [],
        "message": f"특이사항 없음. {msg_detail}",
        "green_times": _make_green_times(east_g, north_g, south_g, west_g),
        "signal_state": _build_signal_state(action),
    }


def evaluate_traffic_control(
    pedestrian_count: int,
    exit_congested: bool,
    accident_detected: bool,
    emergency_detected: bool,
    north_cars: int,
    south_cars: int,
    east_cars: int = 0,
    west_cars: int = 0,
    emergency_vehicle_id: Optional[str] = None,
    priority_direction: Optional[str] = None,
) -> Dict[str, Any]:
    """단일 카메라 요청 또는 병합 상태에서 신호 제어 결과를 생성합니다."""
    base = evaluate_base_traffic(
        pedestrian_count=pedestrian_count,
        exit_congested=exit_congested,
        accident_detected=accident_detected,
        north_cars=north_cars,
        south_cars=south_cars,
        east_cars=east_cars,
        west_cars=west_cars,
    )

    if not emergency_detected:
        return base

    vehicle_id = emergency_vehicle_id or DEFAULT_EMERGENCY_VEHICLE_ID
    direction = (priority_direction or DEFAULT_EMERGENCY_DIRECTION).upper()
    action = "EMERGENCY_CORRIDOR_GREEN"

    return {
        "mode": "EMERGENCY_VEHICLE_PRIORITY",
        "signal_action": action,
        "event_state": "ACTIVE",
        "priority_direction": direction,
        "emergency_vehicle_id": vehicle_id,
        "active_events": [
            {
                "type": "EMERGENCY",
                "direction": direction,
                "vehicle_id": vehicle_id,
            }
        ],
        "message": "[긴급] 응급 차량 접근 감지! 해당 방향 골든타임 확보를 위해 통행로를 우선 개방합니다.",
        # 응급 이벤트 중에도 기존 네 방향 green_times는 일반 주기 값으로 유지
        "green_times": _make_green_times(30, 30, 30, 30),
        "signal_state": _build_signal_state(action),
    }