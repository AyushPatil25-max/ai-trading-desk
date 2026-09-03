def fix():
    with open('backend/execution/dhan_live_execution_engine.py', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    new_lines = []
    skip = False
    for line in lines:
        if 'global_order_tracker.record_success(fingerprint=auth.authorization_id' in line:
            new_lines.append('                global_order_tracker.record_success(fingerprint=auth.authorization_id, order_id=res.order_id, status=res.status.value, details={\"symbol\": req.symbol})\n')
            skip = True
        elif skip and 'return res' in line:
            skip = False
            new_lines.append(line)
        elif not skip:
            new_lines.append(line)
            
    with open('backend/execution/dhan_live_execution_engine.py', 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

fix()
