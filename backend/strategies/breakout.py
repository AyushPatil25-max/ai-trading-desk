import pandas as pd

def breakout_strategy(df: pd.DataFrame) -> pd.DataFrame:
    """
    Generates a BUY signal (1) when:
    - Close > previous 20-day high
    - EMA20 > EMA50 (Bullish Trend)
    - RSI > 50 (Positive Momentum)
    """
    df = df.copy()

    # Find the highest high of the previous 20 days
    df["Previous_High"] = df["High"].rolling(window=20).max().shift(1)

    # Initialize Signal column to 0 (No Trade)
    df["Signal"] = 0

    # Define the Buy Conditions
    conditions = (
        (df["Close"] > df["Previous_High"]) &
        (df["EMA20"] > df["EMA50"]) &
        (df["RSI"] > 50)
    )

    # Apply the Buy Signal (1) where conditions are met
    df.loc[conditions, "Signal"] = 1

    return df

if __name__ == "__main__":
    import sys
    import os
    # Add backend directory to path to allow importing sibling modules
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    from market_data import get_historical_data
    from indicators import calculate_indicators

    print("Running Breakout Strategy on TCS.NS...")
    
    data = get_historical_data("TCS.NS", period="1y")
    data = calculate_indicators(data)
    data = breakout_strategy(data)

    # Filter and display only the days where a BUY signal was generated
    signals = data[data["Signal"] == 1]
    
    if signals.empty:
        print("\nNo BUY signals generated in this period.")
    else:
        print(f"\n--- BUY Signals Found: {len(signals)} ---")
        print(signals[["Date", "Close", "Previous_High", "EMA20", "EMA50", "RSI", "Signal"]].tail())