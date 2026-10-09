from fastapi import APIRouter
from app.schemas.traffic import TrafficData, TrafficResponse
from app.services.logic import evaluate_traffic_control

router = APIRouter(prefix="/api/control", tags=["Control"])

@router.post("/", response_model=TrafficResponse)
def control_traffic(data: TrafficData):
    # 로직 함수 호출하여 결과 반환
    result = evaluate_traffic_control(
        pedestrian_count=data.pedestrian_count,
        exit_congested=data.exit_congested,
        accident_detected=data.accident_detected,
        emergency_detected=data.emergency_detected,
        north_cars=data.north_cars,
        south_cars=data.south_cars
    )
    return result