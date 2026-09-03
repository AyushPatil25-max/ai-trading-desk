def fix():
    with open('backend/execution/dhan_live_execution_engine.py', 'r', encoding='utf-8') as f:
        code = f.read()

    code = code.replace('status=res.status.value', 'status=res.status')
    code = code.replace('\"DHAN_UNAVAILABLE: No client configured.\"', '\"DHAN_CLIENT_MISSING: No client configured.\"')
    
    with open('backend/execution/dhan_live_execution_engine.py', 'w', encoding='utf-8') as f:
        f.write(code)

fix()
