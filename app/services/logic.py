from typing import Dict, Any

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
    
    # 1. 감지된 이벤트 리스트업
    active_events = []
    if emergency_detected:
        active_events.append("EMERGENCY_VEHICLE")
    if accident_detected:
        active_events.append("ACCIDENT")
    if exit_congested:
        active_events.append("EXIT_CONGESTED")
    if pedestrian_count > 5:
        active_events.append("HEAVY_PEDESTRIAN")

    event_count = len(active_events)

    # 2. [단일 이벤트 처리]
    if event_count == 1:
        if emergency_detected:
            return {
                "mode": "EMERGENCY_VEHICLE_PRIORITY",
                "signal_action": "EMERGENCY_CORRIDOR_GREEN",
                "active_events": active_events,
                "message": "[단독] 응급 차량 접근 감지! 해당 진입 방향 신호를 즉시 녹색으로 부여합니다.",
                "green_times": {"north_south_green": 60, "east_west_green": 10}
            }
        elif accident_detected:
            return {
                "mode": "SINGLE_ACCIDENT_LOCKDOWN",
                "signal_action": "ACCIDENT_LANE_RED",
                "active_events": active_events,
                "message": "[단독] 돌발 사고 감지. 해당 사고 구역 진입 신호 적색 고정.",
                "green_times": {"north_south_green": 10, "east_west_green": 10}
            }
        elif exit_congested:
            return {
                "mode": "EXIT_BLOCKED_PROTECTION",
                "signal_action": "HOLD_CURRENT_SIGNAL",
                "active_events": active_events,
                "message": "[단독] 출구 방향 정체 심각: 꼬리물기 방지를 위해 녹색 신호 부여를 일시 보류합니다.",
                "green_times": {"north_south_green": 15, "east_west_green": 15}
            }
        elif pedestrian_count > 5:
            return {
                "mode": "PEDESTRIAN_PROTECTION",
                "signal_action": "PEDESTRIAN_GREEN_EXTENDED",
                "active_events": active_events,
                "message": "[단독] 보행자 밀집 감지: 횡단보도 녹색 신호를 연장합니다.",
                "green_times": {"north_south_green": 20, "east_west_green": 20}
            }

    # 3. [복합 이벤트 처리]
    if event_count >= 2:
        if emergency_detected:
            return {
                "mode": "COMPLEX_EMERGENCY_PRIORITY",
                "signal_action": "EMERGENCY_CORRIDOR_GREEN",
                "active_events": active_events,
                "message": f"[복합 위기] 다중 상황 발생 ({', '.join(active_events)}). 최우선 순위에 따라 응급 차량 통행로를 우선 개방합니다.",
                "green_times": {"north_south_green": 60, "east_west_green": 10}
            }
        elif accident_detected:
            return {
                "mode": "COMPLEX_ACCIDENT_CONTROL",
                "signal_action": "ALL_RED_EXCEPT_BYPASS",
                "active_events": active_events,
                "message": f"[복합 위기] 다중 상황 발생 ({', '.join(active_events)}). 사고 대응 제어를 우선 발동합니다.",
                "green_times": {"north_south_green": 10, "east_west_green": 10}
            }
        elif exit_congested:
            return {
                "mode": "COMPLEX_CONGESTION_CONTROL",
                "signal_action": "HOLD_CURRENT_SIGNAL",
                "active_events": active_events,
                "message": f"[복합 위기] 다중 상황 발생 ({', '.join(active_events)}). 출구 정체 제어를 우선 발동합니다.",
                "green_times": {"north_south_green": 15, "east_west_green": 15}
            }
        else:
            return {
                "mode": "COMPLEX_PEDESTRIAN_CONTROL",
                "signal_action": "PEDESTRIAN_GREEN_EXTENDED",
                "active_events": active_events,
                "message": f"[복합 위기] 다중 상황 발생 ({', '.join(active_events)}). 보행자 보호 제어를 우선 발동합니다.",
                "green_times": {"north_south_green": 20, "east_west_green": 20}
            }

    # 4. [평상시 및 교통 혼잡 제어] (프론트/SUMO 요구사항 반영)
    ns_total = north_cars + south_cars
    ew_total = east_cars + west_cars

    # 남북 방향 정체 시 (CONGESTION_PATTERN)
    if ns_total >= ew_total * 1.5 and ns_total > 5:
        mode = "CONGESTION_PATTERN"
        action = "EXTEND_NORTH_SOUTH_GREEN"
        ns_green = 45
        ew_green = 15
        msg_detail = f"남북 방향 정체 (남북:{ns_total}대 vs 동서:{ew_total}대). 남북 신호 45초 연장."
    # 동서 방향 정체 시 (CONGESTION_PATTERN)
    elif ew_total >= ns_total * 1.5 and ew_total > 5:
        mode = "CONGESTION_PATTERN"
        action = "EXTEND_EAST_WEST_GREEN"
        ns_green = 15
        ew_green = 45
        msg_detail = f"동서 방향 정체 (동서:{ew_total}대 vs 남북:{ns_total}대). 동서 신호 45초 연장."
    # 정상 원활 (NORMAL_PATTERN)
    else:
        mode = "NORMAL_PATTERN"
        action = "REGULAR_CYCLE"
        ns_green = 30
        ew_green = 30
        msg_detail = f"정상 교통 흐름 유지 (남북:{ns_total}대, 동서:{ew_total}대)."

    return {
        "mode": mode,
        "signal_action": action,
        "active_events": [],
        "message": f"특이사항 없음. {msg_detail}",
        "green_times": {
            "north_south_green": ns_green,
            "east_west_green": ew_green
        }
    }