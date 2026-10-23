from pydantic import BaseModel
from typing import List, Optional, Dict, Any

# 클라이언트(시뮬레이터)가 서버로 보내는 요청 데이터 규격
class TrafficData(BaseModel):
    # [추가] 교차로 및 카메라 식별자 (기본값 1)
    intersection_id: int = 1
    camera_id: int = 1
    
    # [추가] AI에서 집계한 전체 차량 수
    vehicle_count: int = 0

    # 기존 요청 데이터 규격
    pedestrian_count: int = 0
    exit_congested: bool = False
    accident_detected: bool = False
    emergency_detected: bool = False
    north_cars: int = 0
    south_cars: int = 0
    east_cars: int = 0
    west_cars: int = 0
    image_frame: Optional[str] = None # Base64 이미지 프레임 수신용

# 서버가 제어 로직 처리 후 반환하는 응답 데이터 규격 (기존 유지)
class TrafficResponse(BaseModel):
    mode: str
    signal_action: str
    active_events: List[str] = []
    message: str
    green_times: Optional[Dict[str, int]] = None
    vehicle_count: Optional[Dict[str, int]] = None
    signal_state: Optional[Dict[str, str]] = None