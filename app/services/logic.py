from typing import Dict, Any

def evaluate_traffic_control(
    pedestrian_count: int,
    exit_congested: bool,
    accident_detected: bool,
    emergency_detected: bool,
    north_cars: int,
    south_cars: int
) -> Dict[str, Any]:
    
    # 1. 감지된 모든 이벤트 리스트업
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

    # 2. [단일 이벤트 처리] 감지된 이벤트가 정확히 1개일 때
    if event_count == 1:
        if emergency_detected:
            return {
                "mode": "EMERGENCY_VEHICLE_PRIORITY",
                "signal_action": "EMERGENCY_CORRIDOR_GREEN",
                "active_events": active_events,
                "message": "[단독] 응급 차량 접근 감지! 해당 진입 방향 신호를 즉시 녹색으로 부여합니다."
            }
        elif accident_detected:
            return {
                "mode": "SINGLE_ACCIDENT_LOCKDOWN",
                "signal_action": "ACCIDENT_LANE_RED",
                "active_events": active_events,
                "message": "[단독] 돌발 사고 감지. 해당 사고 구역 진입 신호 적색 고정."
            }
        elif exit_congested:
            return {
                "mode": "EXIT_BLOCKED_PROTECTION",
                "signal_action": "HOLD_CURRENT_SIGNAL",
                "active_events": active_events,
                "message": "[단독] 출구 방향 정체 심각: 꼬리물기 방지를 위해 녹색 신호 부여를 일시 보류합니다."
            }
        elif pedestrian_count > 5:
            return {
                "mode": "PEDESTRIAN_PROTECTION",
                "signal_action": "PEDESTRIAN_GREEN_EXTENDED",
                "active_events": active_events,
                "message": "[단독] 보행자 밀집 감지: 횡단보도 녹색 신호를 연장합니다."
            }

    # 3. [복합 이벤트 처리] 감지된 이벤트가 2개 이상일 때 (엄격한 우선순위 적용)
    if event_count >= 2:
        if emergency_detected:
            return {
                "mode": "COMPLEX_EMERGENCY_PRIORITY",
                "signal_action": "EMERGENCY_CORRIDOR_GREEN",
                "active_events": active_events,
                "message": f"[복합 위기] 다중 상황 발생 ({', '.join(active_events)}). 최우선 순위에 따라 응급 차량 통행로를 우선 개방합니다."
            }
        elif accident_detected:
            return {
                "mode": "COMPLEX_ACCIDENT_CONTROL",
                "signal_action": "ALL_RED_EXCEPT_BYPASS",
                "active_events": active_events,
                "message": f"[복합 위기] 다중 상황 발생 ({', '.join(active_events)}). 사고 대응 제어를 우선 발동합니다."
            }
        elif exit_congested:
            return {
                "mode": "COMPLEX_CONGESTION_CONTROL",
                "signal_action": "HOLD_CURRENT_SIGNAL",
                "active_events": active_events,
                "message": f"[복합 위기] 다중 상황 발생 ({', '.join(active_events)}). 출구 정체 제어를 우선 발동합니다."
            }
        else:
            return {
                "mode": "COMPLEX_PEDESTRIAN_CONTROL",
                "signal_action": "PEDESTRIAN_GREEN_EXTENDED",
                "active_events": active_events,
                "message": f"[복합 위기] 다중 상황 발생 ({', '.join(active_events)}). 보행자 보호 제어를 우선 발동합니다."
            }

    # 4. [평상시] 이벤트가 전혀 없을 때 (차량 수 통계 기반 적응형 제어)
    dominant_direction = "NORTH" if north_cars >= south_cars else "SOUTH"
    return {
        "mode": "NORMAL",
        "signal_action": "REGULAR_CYCLE",
        "active_events": [],
        "message": f"특이사항 없음. 정상 교통 순환 체계 유지 (우세 방향: {dominant_direction} | 북:{north_cars}, 남:{south_cars})"
    }