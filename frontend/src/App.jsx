import './App.css'

function App() {
  // 이번 주에는 실제 AI/API 대신 테스트용 Mock 데이터를 사용
  const trafficData = {
    vehicles: 23,
    pedestrians: 7,
    emergencyVehicles: 1,
    situation: '응급차량 감지',
  }

  const signals = [
    { direction: '북쪽', status: 'GREEN' },
    { direction: '동쪽', status: 'RED' },
    { direction: '남쪽', status: 'RED' },
    { direction: '서쪽', status: 'RED' },
  ]

  return (
    <div className="dashboard">
      <header className="header">
        <h1>실시간 교통 신호 관제 시스템</h1>
        <p>CCTV 기반 차량·보행자 감지 및 신호 제어</p>
      </header>

      <main className="content">
        <section className="status-section">
          <h2>실시간 상황</h2>

          <div className="card-grid">
            <div className="card">
              <span>차량</span>
              <strong>{trafficData.vehicles}</strong>
              <small>대</small>
            </div>

            <div className="card">
              <span>보행자</span>
              <strong>{trafficData.pedestrians}</strong>
              <small>명</small>
            </div>

            <div className="card">
              <span>응급 차량</span>
              <strong>{trafficData.emergencyVehicles}</strong>
              <small>대</small>
            </div>

            <div className="card situation">
              <span>현재 상황</span>
              <strong>{trafficData.situation}</strong>
            </div>
          </div>
        </section>

        <section className="signal-section">
          <h2>현재 신호 상태</h2>

          <div className="signal-grid">
            {signals.map((signal) => (
              <div className="signal-card" key={signal.direction}>
                <h3>{signal.direction}</h3>
                <div
                  className={`signal-light ${
                    signal.status === 'GREEN' ? 'green' : 'red'
                  }`}
                ></div>
                <strong>{signal.status}</strong>
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  )
}

export default App