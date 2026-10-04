# 🚦 Traffic Control Backend

교통 신호 제어 시스템의 FastAPI 백엔드 서버 리포지토리입니다.

## 🛠️ Tech Stack
* **Language**: Python 3.10+ (최신 버전 권장)
* **Framework**: FastAPI
* **Server**: Uvicorn

---

## ⚙️ Local Development Setup (팀원 설치 가이드)

팀원분들은 본인의 노트북에서 아래 순서대로 빠짐없이 환경을 세팅해 주세요.

### 1. Python 설치 확인 및 준비
먼저 컴퓨터에 파이썬이 설치되어 있는지 확인합니다. (미설치 시 공식 홈페이지에서 Python 3.x 버전 설치)
```bash
python --version
```

### 2. 리포지토리 클론하기
터미널(또는 Git Bash)을 열고 프로젝트를 다운로드할 폴더 경로로 이동한 뒤, 아래 명령어로 소스코드를 복제합니다.
```bash
git clone [https://github.com/jawon02/traffic_control_server.git](https://github.com/jawon02/traffic_control_server.git)
cd traffic_control_server
```

### 3. 필수 패키지 설치
서버 구동과 데이터 검증에 필요한 필수 라이브러리(`fastapi`, `uvicorn`, `pydantic`)를 일괄 설치합니다.
```bash
pip install fastapi uvicorn pydantic
```

### 4. 백엔드 서버 실행하기
설치가 완료되면 아래 명령어를 입력하여 로컬 개발용 실시간 서버를 구동합니다.
```bash
python -m uvicorn app.main:app --reload
```

### 5. API 문서 접속 확인
서버가 정상적으로 켜졌다면 브라우저를 열고 아래 주소로 접속하여 대시보드(Swagger UI)를 확인합니다.
* **Swagger UI Docs**: http://127.0.0.1:8000/docs
