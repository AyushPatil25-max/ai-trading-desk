import logging
import os
import sys
import asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend.application.lifecycle_manager import app_lifespan

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure backend directory is in python search path
current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir))

from market_data import get_live_market_data
from agents.technical_agent import run_technical_agent
from agents.risk_agent import run_risk_agent

app = FastAPI(
    title="AI Trading Desk API", 
    version="1.0",
    lifespan=app_lifespan
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_FILE = current_dir.parent / "frontend" / "index.html"

from fastapi.staticfiles import StaticFiles

# Serve HTML Dashboard
@app.get("/")
def serve_dashboard():
    if not FRONTEND_FILE.exists():
        raise HTTPException(status_code=404, detail=f"File not found at {FRONTEND_FILE}")
    return FileResponse(FRONTEND_FILE)

# Mount the rest of the frontend directory as static files so JS/CSS can be modular
app.mount("/static", StaticFiles(directory=str(current_dir.parent / "frontend")), name="static")

from application.orchestration import analyze_symbol_application
from backend.simulation.routes import router as simulation_router
from backend.scanner.routes import router as scanner_router
from backend.validation.routes import router as validation_router

# Include Simulation, Scanner & Validation Routers
app.include_router(simulation_router)
app.include_router(scanner_router)
app.include_router(validation_router)

from backend.application.alert_routes import alert_router
from backend.application.broker_routes import broker_router
from backend.application.certification_routes import certification_router
from backend.application.context_routes import context_router
from backend.application.distributed_state_routes import distributed_router
from backend.application.evaluation_routes import router as evaluation_router
from backend.application.execution_routes import execution_router
from backend.application.execution_telemetry_routes import execution_telemetry_router
from backend.application.factor_risk_routes import router as factor_risk_router
from backend.application.forward_routes import router as forward_router
from backend.application.forward_validation_routes import forward_validation_router
from backend.application.ipo_routes import router as ipo_router
from backend.application.live_evaluation_routes import router as live_evaluation_router
from backend.application.monitoring_routes import monitoring_router
from backend.application.observability_routes import observability_router
from backend.application.opportunity_routes import router as opportunity_router
from backend.application.orchestration_routes import orchestration_router
from backend.application.provider_routes import provider_router
from backend.application.reliability_routes import reliability_router
from backend.application.replay_routes import replay_router
from backend.application.resilience_routes import resilience_router
from backend.application.robustness_routes import robustness_router
from backend.application.strategy_governance_routes import governance_router
from backend.application.strategy_routes import strategy_router
from backend.application.streaming_routes import streaming_router
from backend.application.telemetry_routes import router as telemetry_router
from backend.application.trading_os_routes import router as trading_os_router
from backend.application.production_routes import production_router

from backend.application.stock_routes import router as stock_router

app.include_router(alert_router)
app.include_router(broker_router)
app.include_router(certification_router)
app.include_router(context_router)
app.include_router(distributed_router)
app.include_router(evaluation_router)
app.include_router(execution_router)
app.include_router(execution_telemetry_router)
app.include_router(factor_risk_router)
app.include_router(forward_router)
app.include_router(forward_validation_router)
app.include_router(ipo_router)
app.include_router(live_evaluation_router)
app.include_router(monitoring_router)
app.include_router(observability_router)
app.include_router(opportunity_router)
app.include_router(orchestration_router)
app.include_router(provider_router)
app.include_router(reliability_router)
app.include_router(replay_router)
app.include_router(resilience_router)
app.include_router(robustness_router)
app.include_router(governance_router)
app.include_router(strategy_router)
app.include_router(streaming_router)
app.include_router(telemetry_router)
app.include_router(trading_os_router)
app.include_router(production_router)
app.include_router(stock_router)

# API Endpoint
@app.get("/api/analyze")
async def analyze_stock(symbol: str = Query(default="TCS.NS")):
    try:
        return await analyze_symbol_application(symbol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # Pass app instance directly without reload to prevent Windows subprocess deadlock
    uvicorn.run(app, host="127.0.0.1", port=5000)
from backend.infrastructure.provider_orchestrator import ResilientProviderOrchestrator
_provider_orchestrator = ResilientProviderOrchestrator()
def get_provider_orchestrator():
    return _provider_orchestrator
