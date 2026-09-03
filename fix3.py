def fix():
    with open('tests/test_phase40_live_execution.py', 'r', encoding='utf-8') as f:
        code = f.read()
    
    code = code.replace(
        'from backend.execution.live_arming_store import global_live_arming_store',
        'from backend.execution.live_arming_store import global_live_arming_store\nfrom backend.execution.live_failure_recovery import global_live_failure_engine'
    )
    
    code = code.replace(
        'global_order_tracker.clear()',
        'global_order_tracker.clear()\n        global_live_failure_engine.clear_reset()'
    )
    
    with open('tests/test_phase40_live_execution.py', 'w', encoding='utf-8') as f:
        f.write(code)

fix()
