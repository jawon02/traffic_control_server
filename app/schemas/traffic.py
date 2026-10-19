from pydantic import BaseModel
from typing import List, Optional, Dict, Any

# 클라이언트(시뮬레이터)가 서버로 보내는 요청 데이터 규격
class TrafficData(BaseModel):
    pedestrian_count: int = 0
    exit_congested: bool = False
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
    green_times: Optional[Dict[str, int]] = None
    vehicle_count: Optional[Dict[str, int]] = None
    signal_state: Optional[Dict[str, str]] = None