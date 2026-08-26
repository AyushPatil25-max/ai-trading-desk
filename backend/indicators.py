import pandas as pd

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates technical indicators using pure pandas.
    """
    df = df.copy()

    # Calculate Exponential Moving Averages (EMA)
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()

    # Calculate Relative Strength Index (RSI - 14 Day)
    delta = df["Close"].diff()
    
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()

    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    return df

if __name__ == "__main__":
    from market_data import get_historical_data
    
    print("Fetching data and calculating indicators for RELIANCE.NS...")
    data = get_historical_data("RELIANCE.NS", period="1y")
    data_with_indicators = calculate_indicators(data)

    print("\n--- Latest Indicator Values ---")
    print(data_with_indicators[["Date", "Close", "EMA20", "EMA50", "RSI"]].tail())