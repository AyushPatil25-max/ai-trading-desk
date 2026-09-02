import sys
import os
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock

# --- MUST BE BEFORE ALL BACKEND IMPORTS ---
os.environ["LIVE_EXECUTION_ENABLED"] = "true"
os.environ["DHAN_ENABLED"] = "true"
os.environ["DHAN_CLIENT_ID"] = "MOCK_CLIENT_ID"
os.environ["DHAN_ACCESS_TOKEN"] = "MOCK_ACCESS_TOKEN"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.domain.broker_schemas import OrderRequest, OrderSide as BrokerOrderSide, OrderType as BrokerOrderType, ProductType as BrokerProductType, ExchangeSegment
from backend.execution.live_arming_store import global_live_arming_store
from backend.execution.operator_authorization_store import global_operator_authorization_store
from backend.execution.controlled_live_execution_orchestrator import global_controlled_live_trade_orchestrator
from backend.adapters.dhan_adapter import DhanBrokerAdapter
from backend.execution.live_readiness import global_live_readiness_engine
from backend.domain.live_readiness_schemas import LiveReadinessReport

def simulate():
    print("--- STARTING MOCK LIVE PATH SIMULATION ---")
    
    # 1. Enable Live Execution Flag is done via os.environ at the top

    # 2. Mock Readiness Engine so it passes
    original_eval = global_live_readiness_engine.evaluate_readiness
    global_live_readiness_engine.evaluate_readiness = lambda *args, **kwargs: LiveReadinessReport(
        is_ready_for_arming=True,
        is_ready_for_order=True,
        overall_status="READY",
        blocking_failures=[],
        warnings=[]
    )

    # 3. Arm the system
    global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)
    print("System Armed:", global_live_arming_store.is_currently_armed())

    # 4. Create Order Domain
    order = OrderRequest(
        symbol="MOCK_TEST",
        side=BrokerOrderSide.BUY,
        quantity=1,
        price=10.0,
        order_type=BrokerOrderType.LIMIT,
        exchange_segment=ExchangeSegment.NSE,
        product_type=BrokerProductType.CNC,
        request_id="test-req-123",
    )

    # 5. Issue Operator Token
    token = global_operator_authorization_store.issue_token(
        operator_id="test_ops",
        order_request=order,
        ttl_seconds=120,
        source="HUMAN_OPERATOR"
    )
    print("Issued Token:", token.token_id)
    print("Order Fingerprint:", token.order_fingerprint)

    # 6. Mock Dhan HTTP Client
    adapter = DhanBrokerAdapter()
    adapter.client = MagicMock()
    adapter.client.request.return_value = {
        "orderId": "dhan-9999",
        "orderStatus": "PENDING",
        "remarks": "Mock response"
    }
    
    # Temporarily patch the adapter in the orchestrator
    global_controlled_live_trade_orchestrator.dhan_adapter = adapter

    # 7. Execute!
    try:
        gate_res, order_rec, broker_res = global_controlled_live_trade_orchestrator.execute_controlled_trade(
            order=order,
            operator_token_id=token.token_id,
            bypass_market_data_for_test=True
        )
        print("Gate Approved:", gate_res.is_approved)
        if not gate_res.is_approved:
            print("Gate Rejection Reason:", gate_res.reason)
            print("Gate Rejection Code:", gate_res.reason_code)
        if broker_res:
            print("Broker Status:", broker_res.status)
            print("Broker Result:", broker_res.model_dump_json())
            print("All Dhan API calls:")
            for call in adapter.client.request.mock_calls:
                print("  ", call)
    except Exception as e:
        print("Exception during execution:", e)
        
    print("--- SIMULATION END ---")

if __name__ == "__main__":
    simulate()
