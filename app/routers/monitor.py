from fastapi import APIRouter

router = APIRouter(prefix="/api/monitor", tags=["Monitoring"])

@router.get("/intersections")
def get_intersections():
    """프론트엔드 관제 지도 및 CCTV 4분할/상세 화면용 교차로 및 카메라 목록 반환"""
    return [
        {
            "intersection_id": 1,
            "intersection_name": "시연 도로",
            "cameras": [
                {"camera_id": 1, "name": "(CCTV 1)"},
                {"camera_id": 2, "name": "(CCTV 2)"},
                {"camera_id": 3, "name": "(CCTV 3)"},
                {"camera_id": 4, "name": "(준비 중)"}
            ]
        },
        {
            "intersection_id": 2,
            "intersection_name": "(준비 중)",
            "cameras": [
                {"camera_id": 1, "name": "(준비 중)"},
                {"camera_id": 2, "name": "(준비 중)"}
            ]
        }
    ]