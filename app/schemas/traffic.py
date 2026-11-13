from pydantic import BaseModel
from typing import List, Optional, Dict, Any

# 클라이언트(시뮬레이터)가 서버로 보내는 요청 데이터 규격
class TrafficData(BaseModel):
    intersection_id: int = 1
    camera_id: int = 1
    vehicle_count: int = 0
    
    # [프론트엔드 관제 요청 규격 필드]
    roi_occupancy_ratio: float = 0.0          # 0.0 ~ 1.0 비율 (예: 0.42)
    roi_congestion_threshold: float = 0.30     # 혼잡 판정 기준 비율 (기본값 0.30)
    exit_congested: bool = False               # 혼잡 여부 (ratio >= threshold)

    pedestrian_count: int = 0
    accident_detected: bool = False
    emergency_detected: bool = False
    north_cars: int = 0
    south_cars: int = 0
    east_cars: int = 0
    west_cars: int = 0
    image_frame: Optional[str] = None # Base64 이미지 프레임 수신용

# 서버가 제어 로직 처리 후 반환하는 응답 데이터 규격
class TrafficResponse(BaseModel):
    mode: str
    signal_action: str
    active_events: List[str] = []
    message: str
    green_times: Optional[Dict[str, int]] = None  # 예: {"east_green": 20, "north_green": 15, "south_green": 15, "west_green": 20}
    vehicle_count: Optional[Dict[str, int]] = None
    signal_state: Optional[Dict[str, str]] = None