import pandas as pd

def backtest(df: pd.DataFrame, initial_capital: float = 100000.0) -> tuple:
    """
    Simulates trading based on generated signals.
    Enters a LONG position on a BUY signal (1).
    Exits the position if RSI drops below 40 or EMA20 crosses below EMA50.
    """
    capital = initial_capital
    position = 0
    entry_price = 0
    trades = []

    for i in range(len(df)):
        price = df["Close"].iloc[i]
        signal = df["Signal"].iloc[i]
        rsi = df["RSI"].iloc[i]
        ema20 = df["EMA20"].iloc[i]
        ema50 = df["EMA50"].iloc[i]
        date = df["Date"].iloc[i].strftime("%Y-%m-%d") if hasattr(df["Date"].iloc[i], "strftime") else str(df["Date"].iloc[i])

        # ENTRY LOGIC
        if signal == 1 and position == 0:
            position = 1
            entry_price = price
            trades.append({
                "type": "BUY",
                "date": date,
                "price": price,
                "index": i
            })

        # EXIT LOGIC (Only if we hold a position)
        elif position == 1:
            # Exit if momentum dies or trend breaks
            if rsi < 40 or ema20 < ema50:
                profit = price - entry_price
                capital += profit
                trades.append({
                    "type": "SELL",
                    "date": date,
                    "price": price,
                    "profit": profit,
                    "index": i
                })
                position = 0

    # Close any open position at the end of the data period
    if position == 1:
        price = df["Close"].iloc[-1]
        date = df["Date"].iloc[-1].strftime("%Y-%m-%d") if hasattr(df["Date"].iloc[-1], "strftime") else str(df["Date"].iloc[-1])
        profit = price - entry_price
        capital += profit
        trades.append({
            "type": "SELL",
            "date": date,
            "price": price,
            "profit": profit,
            "index": len(df) - 1
        })

    return capital, trades

if __name__ == "__main__":
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    from market_data import get_historical_data
    from indicators import calculate_indicators
    from strategies.breakout import breakout_strategy

    print("Running Backtest Engine on TCS.NS...")
    
    # 1. Get Data
    data = get_historical_data("TCS.NS", period="2y")
    # 2. Add Indicators
    data = calculate_indicators(data)
    # 3. Add Signals
    data = breakout_strategy(data)
    
    # 4. Run Simulation
    final_capital, trade_log = backtest(data, initial_capital=100000.0)

    print(f"\nInitial Capital: ₹100,000.00")
    print(f"Final Capital:   ₹{final_capital:,.2f}")
    print(f"Total Return:    {((final_capital - 100000)/100000) * 100:.2f}%\n")
    
    print("--- Trade Ledger ---")
    for trade in trade_log:
        if trade["type"] == "BUY":
            print(f"BUY  | {trade['date']} | Price: ₹{trade['price']:.2f}")
        else:
            profit = trade["profit"]
            result = "WIN" if profit > 0 else "LOSS"
            print(f"SELL | {trade['date']} | Price: ₹{trade['price']:.2f} | Profit: ₹{profit:.2f} ({result})")
            print("-" * 50)