from pydantic import BaseModel
from typing import List, Optional

class TrafficData(BaseModel):
    pedestrian_count: int = 0
    exit_congested: bool = False
    accident_detected: bool = False
    emergency_detected: bool = False
    north_cars: int = 0
    south_cars: int = 0
    east_cars: int = 0
    west_cars: int = 0

class TrafficStatus(BaseModel):
    mode: str
    active_events: List[str]
    message: str
    vehicle_count: Optional[dict] = None
    signal_state: Optional[dict] = None