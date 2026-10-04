from fastapi import APIRouter
from app.schemas.traffic import TrafficData, TrafficStatus

router = APIRouter(prefix="/api/control", tags=["Control"])

@router.post("/", response_model=TrafficStatus)
def control_traffic(data: TrafficData):
    # 1. 이벤트 리스트 생성 및 우선순위 판정
    active_events = []
    if data.emergency_detected:
        active_events.append("EMERGENCY_VEHICLE")
    if data.accident_detected:
        active_events.append("ACCIDENT")
    if data.exit_congested:
        active_events.append("CONGESTION")
    if data.pedestrian_count > 0:
        active_events.append("PEDESTRIAN")

    # 2. 모드 및 메시지 결정
    if "EMERGENCY_VEHICLE" in active_events:
        mode = "EMERGENCY_VEHICLE_PRIORITY"
        message = "응급 차량 접근 감지! 해당 진입 방향 신호를 즉시 녹색으로 부여합니다."
    elif "ACCIDENT" in active_events:
        mode = "ACCIDENT_PRIORITY"
        message = "돌발 사고 감지! 안전 확보를 위한 신호 제어를 실행합니다."
    else:
        mode = "NORMAL_MODE"
        message = "원활한 교통 흐름을 위한 기본 적응형 신호 제어 중입니다."

    # 3. 프론트엔드 전달용 응답 데이터 조립
    return {
        "mode": mode,
        "active_events": active_events,
        "message": message,
        "vehicle_count": {
            "north_cars": data.north_cars,
            "south_cars": data.south_cars,
            "east_cars": data.east_cars,
            "west_cars": data.west_cars
        },
        "signal_state": {
            "north": "GREEN" if mode == "EMERGENCY_VEHICLE_PRIORITY" else "RED",
            "south": "RED",
            "east": "RED",
            "west": "RED"
        }
    }