def calculate_metrics(trades: list, initial_capital: float, final_capital: float) -> dict:
    """
    Processes a trade log and calculates key performance metrics.
    """
    sell_trades = [t for t in trades if t.get("type") == "SELL"]
    total_trades = len(sell_trades)

    if total_trades == 0:
        return {"Error": "No completed trades to analyze."}

    winning_trades = [t for t in sell_trades if t["profit"] > 0]
    losing_trades = [t for t in sell_trades if t["profit"] <= 0]

    win_rate = (len(winning_trades) / total_trades) * 100

    gross_profit = sum(t["profit"] for t in winning_trades)
    gross_loss = abs(sum(t["profit"] for t in losing_trades))

    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss != 0 else float('inf')
    
    avg_win = round(gross_profit / len(winning_trades), 2) if winning_trades else 0.0
    avg_loss = round(gross_loss / len(losing_trades), 2) if losing_trades else 0.0

    return {
        "Total Trades": total_trades,
        "Win Rate (%)": round(win_rate, 2),
        "Profit Factor": profit_factor,
        "Total P&L (₹)": round(final_capital - initial_capital, 2),
        "Avg Winning Trade (₹)": avg_win,
        "Avg Losing Trade (₹)": avg_loss
    }

if __name__ == "__main__":
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    from market_data import get_historical_data
    from indicators import calculate_indicators
    from strategies.breakout import breakout_strategy
    from backtesting.engine import backtest

    print("Generating Performance Analytics for TCS.NS...\n")
    
    # Run the pipeline
    data = get_historical_data("TCS.NS", period="2y")
    data = calculate_indicators(data)
    data = breakout_strategy(data)
    initial_cap = 100000.0
    final_cap, trade_log = backtest(data, initial_capital=initial_cap)

    # Calculate metrics
    stats = calculate_metrics(trade_log, initial_cap, final_cap)

    # Display clean, dashboard-style output
    print("┌─────────────────────────────────────────┐")
    print("│         STRATEGY PERFORMANCE            │")
    print("├─────────────────────────────────────────┤")
    for key, value in stats.items():
        print(f"│ {key:<25} | {value:>11} │")
    print("└─────────────────────────────────────────┘")