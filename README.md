# AI Quantitative Trading Desk & Trading OS

Autonomous multi-agent quantitative research, continuous opportunity discovery, risk management, and simulated execution platform.

---

## 1. Local Deployment & Startup Procedure

### Prerequisites
- Python 3.10+ (Recommended: 3.11/3.14)
- Virtual environment configured in `./venv`

### Backend Startup Command
To start the unified FastAPI server and dashboard:
```powershell
.\venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 5000
```
*(Alternatively: `.\venv\Scripts\python.exe backend/main.py`)*

### Frontend Startup Command
The frontend is a lightweight Single-Page Application (`frontend/index.html`) natively served by the FastAPI backend at root `/`.
- No Node.js build step or separate server is required.
- Starting the backend automatically starts and serves the frontend.

### Service URLs
- **Frontend Dashboard:** [http://127.0.0.1:5000/](http://127.0.0.1:5000/)
- **Backend API Docs (Swagger UI):** [http://127.0.0.1:5000/docs](http://127.0.0.1:5000/docs)
- **OpenAPI JSON Specification:** [http://127.0.0.1:5000/openapi.json](http://127.0.0.1:5000/openapi.json)

### Health Check & System Readiness
- **Endpoint:** `GET /api/telemetry/health`
- **Verification Command:**
```powershell
curl http://127.0.0.1:5000/api/telemetry/health
```
- **Healthy Response:**
```json
{
  "api_status": "HEALTHY",
  "paper_broker_status": "HEALTHY",
  "preflight_status": "HEALTHY",
  "portfolio_ledger_status": "HEALTHY",
  "telemetry_status": "HEALTHY",
  "kill_switch_state": "ARMED",
  "data_freshness": "FRESH",
  "error_count": 0,
  "healthy": true
}
```

---

## 2. Environment Configuration

Create a `.env` file in the project root:
```ini
# Optional LLM Inference Key (Groq Cloud)
GROQ_API_KEY=your_groq_api_key_here
```

> [!NOTE]
> All core quantitative screening, 17-stage orchestration, risk management, position sizing, pre-flight checks, paper brokerage, and evaluation harnesses function deterministically without external API credentials.

---

## 3. Paper-Trading Safety & Real-Money Isolation

> [!CAUTION]
> **STRICT SAFETY ENFORCEMENT**:
> - **NO REAL MONEY**: Zero real-money accounts, exchange credentials, or production broker connections.
> - **PAPER & SANDBOX ONLY**: All order routing is coordinated via `BrokerManager`, supporting `PaperBrokerAdapter` (internal simulation) and `SandboxBrokerAdapter` (external broker sandbox/paper API). Real-money live broker execution (`LIVE`) is unconditionally prohibited and fails closed.
> - **PRE-FLIGHT GATEKEEPER**: No order may bypass the Pre-Flight gatekeeper or deterministic risk sizing floors.
> - **EMERGENCY KILL SWITCH**: An operator kill switch is accessible via `POST /api/telemetry/kill-switch` to immediately block all simulated execution.

---

## 4. Running Tests

Run the complete regression test suite:
```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

Run dedicated test suites:
- **Phase 29 (Automated Strategy Governance & Champion/Challenger Validation):** `.\venv\Scripts\python.exe -m unittest tests/test_strategy_governance_e2e.py`
- **Phase 28 (Distributed State, Persistent Recovery & Multi-Node Coordination):** `.\venv\Scripts\python.exe -m unittest tests/test_distributed_state_recovery_e2e.py`
- **Phase 27 (Production Readiness, Deployment Hardening & System Certification):** `.\venv\Scripts\python.exe -m unittest tests/test_production_readiness_e2e.py`
- **Phase 26 (Forward Paper Trading, Shadow Validation & Drift Monitoring):** `.\venv\Scripts\python.exe -m unittest tests/test_forward_validation_e2e.py`
- **Phase 25 (Strategy Robustness, Regime Analysis & Monte Carlo Validation):** `.\venv\Scripts\python.exe -m unittest tests/test_strategy_robustness_e2e.py`
- **Phase 24 (Deterministic Historical Replay & Walk-Forward Validation):** `.\venv\Scripts\python.exe -m unittest tests/test_deterministic_historical_replay_e2e.py`
- **Phase 23 (Production Observability, Audit Integrity & Operational Control):** `.\venv\Scripts\python.exe -m unittest tests/test_observability_audit_integrity_e2e.py`
- **Phase 22 (System Resilience, Failure Injection & Automated Recovery):** `.\venv\Scripts\python.exe -m unittest tests/test_system_resilience_recovery_e2e.py`
- **Phase 22 (Centralized Alerting & Compliance Audit Trail):** `.\venv\Scripts\python.exe -m unittest tests/test_alerting_compliance_audit_e2e.py`
- **Phase 21 (Data Provider Orchestration & Resiliency):** `.\venv\Scripts\python.exe -m unittest tests/test_provider_orchestration_resiliency_e2e.py`
- **Phase 19 (Reliability, Stress Testing & Operational Readiness):** `.\venv\Scripts\python.exe -m unittest tests/test_system_reliability_e2e.py`
- **Phase 18 (Real-Time Streaming & Telemetry):** `.\venv\Scripts\python.exe -m unittest tests/test_realtime_streaming_e2e.py`
- **Phase 17 (Statistical Factors & Risk Optimization):** `.\venv\Scripts\python.exe -m unittest tests/test_statistical_factor_risk_optimization_e2e.py`
- **Phase 16 (Live Evaluation & Staged Broker Execution):** `.\venv\Scripts\python.exe -m unittest tests/test_live_evaluation_staged_execution_e2e.py`
- **Phase 15 (Broker Integration & Sandbox Connectivity):** `.\venv\Scripts\python.exe -m unittest tests/test_broker_sandbox_integration_e2e.py`
- **Phase 14 (Dashboard & Multi-Agent Visualizer):** `.\venv\Scripts\python.exe -m unittest tests/test_dashboard_frontend_e2e.py`
- **Phase 13 (Broker Integration & Execution Adapter):** `.\venv\Scripts\python.exe -m unittest tests/test_broker_adapter_e2e.py`
- **Phase 13 (Real-Time Monitoring & System Health):** `.\venv\Scripts\python.exe -m unittest tests/test_system_health_monitoring_e2e.py`
- **Phase 12 (Live Forward Paper Trading):** `.\venv\Scripts\python.exe -m unittest tests/test_forward_simulation_e2e.py`
- **Phase 11 (Historical Evaluation Harness):** `.\venv\Scripts\python.exe -m unittest tests/test_evaluation_harness_e2e.py`
- **Phase 10 (Opportunity Scanner):** `.\venv\Scripts\python.exe -m unittest tests/test_opportunity_scanner_e2e.py`
- **Phase 9 (End-to-End Trading OS):** `.\venv\Scripts\python.exe -m unittest tests/test_trading_os_e2e.py`

---

## 5. Shutdown Procedure

To cleanly stop the local server:
1. In the terminal running the server, press `Ctrl + C`.
2. To terminate a background process on Windows:
```powershell
Get-Process python | Where-Object { $_.CommandLine -like "*uvicorn*" } | Stop-Process -Force
```
