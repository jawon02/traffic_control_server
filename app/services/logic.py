def evaluate_traffic_control(
    pedestrian_count: int,
    exit_congested: bool,
    accident_detected: bool,
    emergency_detected: bool,
    north_cars: int,
    south_cars: int
) -> dict:
    
    # 1. [최우선] 응급 차량 진입 시 긴급 신호 제어
    if emergency_detected:
        return {
            "mode": "EMERGENCY_VEHICLE_PRIORITY",
            "signal_action": "ALL_GREEN_FOR_EMERGENCY",
            "message": "응급 차량 접근 감지! 해당 진입 방향 신호를 즉시 녹색으로 부여합니다."
        }

    # 2. [비상 락다운 모드] 돌발 사고 감지 시
    if accident_detected:
        return {
            "mode": "EMERGENCY_LOCKDOWN",
            "signal_action": "ALL_RED_FIXED",
            "message": "돌발 사고 감지! 모든 진입 신호를 적색으로 고정하고 우회로를 안내합니다."
        }

    # 3. [출구 공간 감지 모드] 꼬리물기 방지
    if exit_congested:
        return {
            "mode": "EXIT_BLOCKED_PROTECTION",
            "signal_action": "HOLD_CURRENT_SIGNAL",
            "message": "출구 방향 정체 심각: 꼬리물기 방지를 위해 녹색 신호 부여를 일시 보류합니다."
        }

    # 4. 기본 평상시 상태
    return {
        "mode": "NORMAL",
        "signal_action": "REGULAR_CYCLE",
        "message": "특이사항 없음. 정상 신호 체계를 유지합니다."
    }