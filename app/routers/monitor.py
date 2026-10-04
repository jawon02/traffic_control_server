from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["Monitoring"])

@router.get("/intersections")
def get_intersections():
    """프론트엔드 종합 상황도용 교차로 목록 반환"""
    return [
        {
            "intersection_id": "intersection_01",
            "intersection_name": "OO사거리"
        },
        {
            "intersection_id": "intersection_02",
            "intersection_name": "대학입구"
        }
    ]