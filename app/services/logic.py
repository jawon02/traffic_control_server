from typing import Dict, Any, List

# 이벤트별 우선순위 가중치 (Scoring Matrix)
EVENT_WEIGHTS = {
    "EMERGENCY_VEHICLE": 100,  # 최우선 (골든타임 확보)
    "ACCIDENT": 80,            # 2차 사고 방지
    "EXIT_CONGESTED": 40,      # 교차로 꼬리물기 차단
    "HEAVY_PEDESTRIAN": 20,    # 보행자 안전
}


def _build_signal_state(action: str) -> Dict[str, str]:
    """신호 제어 액션에 따라 4방향(N/S/E/W) 개별 신호 상태를 동적으로 생성합니다."""
    if action == "EMERGENCY_CORRIDOR_GREEN":
        return {"north": "GREEN", "south": "GREEN", "east": "RED", "west": "RED"}
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


def evaluate_traffic_control(
    pedestrian_count: int,
    exit_congested: bool,
    accident_detected: bool,
    emergency_detected: bool,
    north_cars: int,
    south_cars: int,
    east_cars: int = 0,
    west_cars: int = 0
) -> Dict[str, Any]:
    
    active_events: List[str] = []
    total_risk_score = 0

    if emergency_detected:
        active_events.append("EMERGENCY_VEHICLE")
        total_risk_score += EVENT_WEIGHTS["EMERGENCY_VEHICLE"]
    if accident_detected:
        active_events.append("ACCIDENT")
        total_risk_score += EVENT_WEIGHTS["ACCIDENT"]
    if exit_congested:
        active_events.append("EXIT_CONGESTED")
        total_risk_score += EVENT_WEIGHTS["EXIT_CONGESTED"]
    if pedestrian_count > 5:
        active_events.append("HEAVY_PEDESTRIAN")
        total_risk_score += EVENT_WEIGHTS["HEAVY_PEDESTRIAN"]

    event_count = len(active_events)

    # 1. [단일 돌발 상황 제어]
    if event_count == 1:
        if emergency_detected:
            action = "EMERGENCY_CORRIDOR_GREEN"
            return {
                "mode": "EMERGENCY_VEHICLE_PRIORITY",
                "signal_action": action,
                "active_events": active_events,
                "message": "[긴급] 응급 차량 접근 감지! 해당 방향 골든타임 확보를 위해 통행로를 우선 개방합니다.",
                "green_times": {"east_green": 10, "north_green": 30, "south_green": 30, "west_green": 10},
                "signal_state": _build_signal_state(action)
            }
        elif accident_detected:
            action = "ACCIDENT_LANE_RED"
            return {
                "mode": "SINGLE_ACCIDENT_LOCKDOWN",
                "signal_action": action,
                "active_events": active_events,
                "message": "[위험] 돌발 사고 감지! 2차 추돌 방지를 위해 해당 구간 진입 신호를 적색으로 고정합니다.",
                "green_times": {"east_green": 10, "north_green": 10, "south_green": 10, "west_green": 10},
                "signal_state": _build_signal_state(action)
            }
        elif exit_congested:
            action = "HOLD_CURRENT_SIGNAL"
            return {
                "mode": "EXIT_BLOCKED_PROTECTION",
                "signal_action": action,
                "active_events": active_events,
                "message": "[경고] 출구 방향 정체 심각: 교차로 내 꼬리물기 차단을 위해 진행 신호를 일시 보류합니다.",
                "green_times": {"east_green": 15, "north_green": 15, "south_green": 15, "west_green": 15},
                "signal_state": _build_signal_state(action)
            }
        elif pedestrian_count > 5:
            action = "EXTEND_NORTH_SOUTH_GREEN"
            return {
                "mode": "PEDESTRIAN_PROTECTION",
                "signal_action": "PEDESTRIAN_GREEN_EXTENDED",
                "active_events": active_events,
                "message": "[주의] 보행자 밀집 감지: 보행자 안전 확보를 위해 횡단 신호를 연장합니다.",
                "green_times": {"east_green": 15, "north_green": 25, "south_green": 25, "west_green": 15},
                "signal_state": _build_signal_state(action)
            }

    # 2. [복합 다중 위기 상황 제어]
    if event_count >= 2:
        if emergency_detected:
            action = "EMERGENCY_CORRIDOR_GREEN"
            return {
                "mode": "COMPLEX_EMERGENCY_PRIORITY",
                "signal_action": action,
                "active_events": active_events,
                "message": f"[복합 위기 (Score: {total_risk_score})] 다중 제어 발동. 응급 통행로를 우선 확보합니다.",
                "green_times": {"east_green": 10, "north_green": 30, "south_green": 30, "west_green": 10},
                "signal_state": _build_signal_state(action)
            }
        elif accident_detected:
            action = "ALL_RED_EXCEPT_BYPASS"
            return {
                "mode": "COMPLEX_ACCIDENT_CONTROL",
                "signal_action": action,
                "active_events": active_events,
                "message": f"[복합 위기 (Score: {total_risk_score})] 사고 구간 안전 락다운 및 전면 적색을 제어합니다.",
                "green_times": {"east_green": 10, "north_green": 10, "south_green": 10, "west_green": 10},
                "signal_state": _build_signal_state(action)
            }
        elif exit_congested:
            action = "HOLD_CURRENT_SIGNAL"
            return {
                "mode": "COMPLEX_CONGESTION_CONTROL",
                "signal_action": action,
                "active_events": active_events,
                "message": f"[복합 위기 (Score: {total_risk_score})] 출구 정체 차단 모드를 우선 제어합니다.",
                "green_times": {"east_green": 15, "north_green": 15, "south_green": 15, "west_green": 15},
                "signal_state": _build_signal_state(action)
            }

    # 3. [평상시 및 방향별 대기열 기반 동적 신호 제어]
    ns_total = north_cars + south_cars
    ew_total = east_cars + west_cars

    if ns_total >= ew_total * 1.5 and ns_total > 5:
        mode = "CONGESTION_PATTERN"
        action = "EXTEND_NORTH_SOUTH_GREEN"
        north_g, south_g, east_g, west_g = 40, 40, 15, 15
        msg_detail = f"남북 대기열 정체 (남북:{ns_total}대 vs 동서:{ew_total}대). 남북 녹색 시간 연장."
    elif ew_total >= ns_total * 1.5 and ew_total > 5:
        mode = "CONGESTION_PATTERN"
        action = "EXTEND_EAST_WEST_GREEN"
        north_g, south_g, east_g, west_g = 15, 15, 40, 40
        msg_detail = f"동서 대기열 정체 (동서:{ew_total}대 vs 남북:{ns_total}대). 동서 녹색 시간 연장."
    else:
        mode = "NORMAL_PATTERN"
        action = "REGULAR_CYCLE"
        north_g, south_g, east_g, west_g = 30, 30, 30, 30
        msg_detail = f"정상 교통 흐름 (남북:{ns_total}대, 동서:{ew_total}대)."

    return {
        "mode": mode,
        "signal_action": action,
        "active_events": [],
        "message": f"특이사항 없음. {msg_detail}",
        "green_times": {
            "east_green": east_g,
            "north_green": north_g,
            "south_green": south_g,
            "west_green": west_g
        },
        "signal_state": _build_signal_state(action)
    }