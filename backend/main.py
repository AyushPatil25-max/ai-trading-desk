import os
import sys
import asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Ensure backend directory is in python search path
current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir))

from market_data import get_live_market_data
from agents.technical_agent import run_technical_agent
from agents.risk_agent import run_risk_agent

app = FastAPI(title="AI Trading Desk API")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_FILE = current_dir.parent / "frontend" / "index.html"

# Serve HTML Dashboard
@app.get("/")
def serve_dashboard():
    if not FRONTEND_FILE.exists():
        raise HTTPException(status_code=404, detail=f"File not found at {FRONTEND_FILE}")
    return FileResponse(FRONTEND_FILE)

from application.orchestration import analyze_symbol_application
from backend.simulation.routes import router as simulation_router
from backend.scanner.routes import router as scanner_router
from backend.validation.routes import router as validation_router

# Include Simulation, Scanner & Validation Routers
app.include_router(simulation_router)
app.include_router(scanner_router)
app.include_router(validation_router)

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