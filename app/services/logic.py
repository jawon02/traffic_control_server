from typing import Dict, Any, List

# 이벤트별 우선순위 가중치 (Scoring Matrix)
EVENT_WEIGHTS = {
    "EMERGENCY_VEHICLE": 100,  # 최우선 (골든타임 확보)
    "ACCIDENT": 80,            # 2차 사고 방지
    "EXIT_CONGESTED": 40,      # 교차로 꼬리물기 차단
    "HEAVY_PEDESTRIAN": 20,    # 보행자 안전
}


def _build_signal_state(action: str, target_direction: str = "north_south") -> Dict[str, str]:
    """신호 제어 액션에 따라 4방향(N/S/E/W) 개별 신호 상태를 동적으로 생성합니다."""
    if action == "EMERGENCY_CORRIDOR_GREEN":
        # 응급차량 진입 방향 녹색, 타 방향 적색 차단
        return {"north": "GREEN", "south": "GREEN", "east": "RED", "west": "RED"}
    elif action == "ACCIDENT_LANE_RED":
        # 사고 발생 차선 진입 금지(RED), 나머지 우회/안전 서행
        return {"north": "RED", "south": "RED", "east": "YELLOW", "west": "YELLOW"}
    elif action == "ALL_RED_EXCEPT_BYPASS":
        # 복합 사고 시 교차로 전체 전면 적색 차단
        return {"north": "RED", "south": "RED", "east": "RED", "west": "RED"}
    elif action == "HOLD_CURRENT_SIGNAL":
        # 꼬리물기 방지 신호 보류
        return {"north": "RED", "south": "RED", "east": "RED", "west": "RED"}
    elif action == "EXTEND_NORTH_SOUTH_GREEN":
        return {"north": "GREEN", "south": "GREEN", "east": "RED", "west": "RED"}
    elif action == "EXTEND_EAST_WEST_GREEN":
        return {"north": "RED", "south": "RED", "east": "GREEN", "west": "GREEN"}
    else:
        # 일반 시클릭 패턴
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
    
    # 1. 감지된 이벤트 리스트업 및 위기 스코어(Risk Score) 계산
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

    # 2. [단일 돌발 상황 제어]
    if event_count == 1:
        if emergency_detected:
            action = "EMERGENCY_CORRIDOR_GREEN"
            return {
                "mode": "EMERGENCY_VEHICLE_PRIORITY",
                "signal_action": action,
                "active_events": active_events,
                "message": "[긴급] 응급 차량 접근 감지! 해당 방향 골든타임 확보를 위해 통행로를 우선 개방합니다.",
                "green_times": {"north_south_green": 60, "east_west_green": 10},
                "signal_state": _build_signal_state(action)
            }
        elif accident_detected:
            action = "ACCIDENT_LANE_RED"
            return {
                "mode": "SINGLE_ACCIDENT_LOCKDOWN",
                "signal_action": action,
                "active_events": active_events,
                "message": "[위험] 돌발 사고 감지! 2차 추돌 방지를 위해 해당 구간 진입 신호를 적색으로 고정합니다.",
                "green_times": {"north_south_green": 10, "east_west_green": 10},
                "signal_state": _build_signal_state(action)
            }
        elif exit_congested:
            action = "HOLD_CURRENT_SIGNAL"
            return {
                "mode": "EXIT_BLOCKED_PROTECTION",
                "signal_action": action,
                "active_events": active_events,
                "message": "[경고] 출구 방향 정체 심각: 교차로 내 꼬리물기 차단을 위해 진행 신호를 일시 보류합니다.",
                "green_times": {"north_south_green": 15, "east_west_green": 15},
                "signal_state": _build_signal_state(action)
            }
        elif pedestrian_count > 5:
            action = "EXTEND_NORTH_SOUTH_GREEN"
            return {
                "mode": "PEDESTRIAN_PROTECTION",
                "signal_action": "PEDESTRIAN_GREEN_EXTENDED",
                "active_events": active_events,
                "message": "[주의] 보행자 밀집 감지: 보행자 안전 확보를 위해 횡단 신호를 연장합니다.",
                "green_times": {"north_south_green": 20, "east_west_green": 20},
                "signal_state": _build_signal_state(action)
            }

    # 3. [복합 다중 위기 상황 제어 - 스코어 기반 동적 처리]
    if event_count >= 2:
        if emergency_detected:
            action = "EMERGENCY_CORRIDOR_GREEN"
            return {
                "mode": "COMPLEX_EMERGENCY_PRIORITY",
                "signal_action": action,
                "active_events": active_events,
                "message": f"[복합 위기 (Score: {total_risk_score})] 다중 제어 발동 ({', '.join(active_events)}). 최우선 가중치에 따라 응급 통행로를 확보합니다.",
                "green_times": {"north_south_green": 60, "east_west_green": 10},
                "signal_state": _build_signal_state(action)
            }
        elif accident_detected:
            action = "ALL_RED_EXCEPT_BYPASS"
            return {
                "mode": "COMPLEX_ACCIDENT_CONTROL",
                "signal_action": action,
                "active_events": active_events,
                "message": f"[복합 위기 (Score: {total_risk_score})] 다중 제어 발동 ({', '.join(active_events)}). 사고 구간 안전 락다운 및 전면 적색을 제어합니다.",
                "green_times": {"north_south_green": 10, "east_west_green": 10},
                "signal_state": _build_signal_state(action)
            }
        elif exit_congested:
            action = "HOLD_CURRENT_SIGNAL"
            return {
                "mode": "COMPLEX_CONGESTION_CONTROL",
                "signal_action": action,
                "active_events": active_events,
                "message": f"[복합 위기 (Score: {total_risk_score})] 출구 정체 차단 모드를 우선 제어합니다.",
                "green_times": {"north_south_green": 15, "east_west_green": 15},
                "signal_state": _build_signal_state(action)
            }

    # 4. [평상시 동적 ROI 대기열 혼잡도 연장 제어]
    ns_total = north_cars + south_cars
    ew_total = east_cars + west_cars

    if ns_total >= ew_total * 1.5 and ns_total > 5:
        mode = "CONGESTION_PATTERN"
        action = "EXTEND_NORTH_SOUTH_GREEN"
        ns_green, ew_green = 45, 15
        msg_detail = f"남북 대기열 정체 (남북:{ns_total}대 vs 동서:{ew_total}대). 남북 신호 45초 연장."
    elif ew_total >= ns_total * 1.5 and ew_total > 5:
        mode = "CONGESTION_PATTERN"
        action = "EXTEND_EAST_WEST_GREEN"
        ns_green, ew_green = 15, 45
        msg_detail = f"동서 대기열 정체 (동서:{ew_total}대 vs 남북:{ns_total}대). 동서 신호 45초 연장."
    else:
        mode = "NORMAL_PATTERN"
        action = "REGULAR_CYCLE"
        ns_green, ew_green = 30, 30
        msg_detail = f"정상 교통 흐름 (남북:{ns_total}대, 동서:{ew_total}대)."

    return {
        "mode": mode,
        "signal_action": action,
        "active_events": [],
        "message": f"특이사항 없음. {msg_detail}",
        "green_times": {
            "north_south_green": ns_green,
            "east_west_green": ew_green
        },
        "signal_state": _build_signal_state(action)
    }