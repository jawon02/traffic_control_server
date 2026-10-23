from fastapi import APIRouter

router = APIRouter(prefix="/api/monitor", tags=["Monitoring"])

@router.get("/intersections")
def get_intersections():
    """프론트엔드 관제 지도 및 CCTV 4분할/상세 화면용 교차로 및 카메라 목록 반환"""
    return [
        {
            "intersection_id": 1,
            "intersection_name": "조선대 사거리",
            "cameras": [
                {"camera_id": 1, "name": "북측 진입로 (CCTV 1)"},
                {"camera_id": 2, "name": "남측 진입로 (CCTV 2)"},
                {"camera_id": 3, "name": "동측 진입로 (CCTV 3)"},
                {"camera_id": 4, "name": "서측 진입로 (준비 중)"}
            ]
        },
        {
            "intersection_id": 2,
            "intersection_name": "대학입구 삼거리",
            "cameras": [
                {"camera_id": 1, "name": "정문 진입로"},
                {"camera_id": 2, "name": "후문 진입로"}
            ]
        }
    ]