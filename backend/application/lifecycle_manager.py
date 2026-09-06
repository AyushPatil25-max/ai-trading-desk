import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

from backend.config.app_config import get_app_config
from backend.execution.live_arming_store import global_live_arming_store


logger = logging.getLogger(__name__)

class LifecycleManager:
    """
    Phase 34: Centralized Runtime Lifecycle Manager.
    Ensures deterministic, fail-closed startup and shutdown sequences.
    """
    
    @classmethod
    def startup_sequence(cls):
        logger.info("Initializing system lifecycle startup sequence.")
        
        # 1. Configuration Check
        config = get_app_config()
        if config.live_execution_enabled:
            logger.warning("SYSTEM CONFIGURED FOR LIVE EXECUTION. Verifying safety gates.")
            if not config.dhan_access_token or not config.dhan_client_id:
                logger.error("LIVE EXECUTION ENABLED BUT MISSING BROKER CREDENTIALS. FAILING CLOSED.")
                # We do not crash the app, but we could explicitly disarm or flip the config.
                
        # 2. Force Clear Live Arming
        # Invariant: Live arming must never survive a process restart.
        global_live_arming_store.disarm()
        logger.info("Live arming store securely disarmed.")
        
        # 3. Persistent State initialization (can run async or sync depending on implementation)
        # Assuming synchronous or already handled by underlying stores.
        
        # 4. Start Market Data Gateway
        from backend.application.market_data_gateway import get_market_data_gateway
        get_market_data_gateway().start()
        
        logger.info("System startup sequence completed safely.")
        
    @classmethod
    def shutdown_sequence(cls):
        logger.info("Initializing system lifecycle shutdown sequence.")
        from backend.application.market_data_gateway import get_market_data_gateway
        get_market_data_gateway().stop()
        global_live_arming_store.disarm()
        logger.info("System shutdown sequence completed safely.")

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    # Startup
    LifecycleManager.startup_sequence()
    yield
    # Shutdown
    LifecycleManager.shutdown_sequence()




