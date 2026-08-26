import yfinance as yf
import pandas as pd
import json

def get_live_market_data(symbol: str) -> dict:
    """
    Fetches live stock data and calculates technical indicators using pure Pandas.
    """
    # 1. Download the last 60 days of daily data
    ticker = yf.Ticker(symbol)
    df = ticker.history(period="60d")
    
    if df.empty:
        raise ValueError(f"Could not fetch data for {symbol}. Check the ticker symbol.")

    # 2. Calculate Indicators manually with Pandas (Bypassing the numba error)
    
    # EMA (Exponential Moving Average)
    df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    
    # RSI (14-day Relative Strength Index)
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = avg_gain / avg_loss
    df['RSI_14'] = 100 - (100 / (1 + rs))
    
    # 20-Day High
    df['20_day_high'] = df['High'].rolling(window=20).max()

    # 3. Extract the most recent day's row
    latest = df.iloc[-1]
    
    # 4. Format as a clean dictionary for our AI Agent
    market_data = {
        "latest_close": round(float(latest['Close']), 2),
        "20_day_high": round(float(latest['20_day_high']), 2),
        "ema20": round(float(latest['EMA_20']), 2),
        "ema50": round(float(latest['EMA_50']), 2),
        "rsi": round(float(latest['RSI_14']), 2)
    }
    
    return market_data

if __name__ == "__main__":
    print("Fetching live market data for TCS.NS...")
    
    try:
        live_data = get_live_market_data("TCS.NS")
        print("\n--- Live Data Engine Output ---")
        print(json.dumps(live_data, indent=2))
    except Exception as e:
        print(f"Error: {e}")