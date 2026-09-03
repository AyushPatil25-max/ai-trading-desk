from backend.config.app_config import get_app_config
import os
import json
import asyncio
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from groq import AsyncGroq

# Load environment variables from .env
load_dotenv()

# 1. Define the exact JSON structure the AI must return
class TechnicalAnalysis(BaseModel):
    symbol: str = Field(description="The ticker symbol of the asset")
    trend: str = Field(description="The current market trend (BULLISH, BEARISH, or NEUTRAL)")
    setup: str = Field(description="The identified trading setup (e.g., BREAKOUT, PULLBACK, REVERSAL, NONE)")
    technical_score: float = Field(description="A conviction score from 1.0 to 10.0 based on the technicals")
    confirmation: bool = Field(description="True if the technical indicators confirm a valid trade, False otherwise")

# 2. Build the Live AI Agent function
async def run_technical_agent(symbol: str, recent_data: dict) -> TechnicalAnalysis:
    """
    Analyzes raw market data using Groq and returns a structured technical thesis asynchronously.
    """
    api_key = get_app_config().groq_api_key
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set in .env")
        
    client = AsyncGroq(api_key=api_key)
    
    # We pass the schema so the model knows exactly what JSON format to build
    schema_json = json.dumps(TechnicalAnalysis.model_json_schema(), indent=2)
    
    prompt = f"""
    You are an expert technical analyst for a quantitative trading desk.
    Analyze the following recent market data for {symbol}:
    {json.dumps(recent_data, indent=2)}
    
    Determine the trend, the best trading setup, and provide a conviction score.
    You must output ONLY valid JSON that matches this exact schema:
    {schema_json}
    """
    
    # Call Groq's API using the configured model
    chat_completion = await client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": "You are a specialized financial AI that only outputs raw, valid JSON."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        model="openai/gpt-oss-120b", 
        response_format={"type": "json_object"}, 
        temperature=0.1, 
    )
    
    # Validate the AI's response against our Pydantic model
    response_text = chat_completion.choices[0].message.content
    return TechnicalAnalysis.model_validate_json(response_text)

if __name__ == "__main__":
    print("Running Live Technical Agent via Groq...")
    
    # Simulated data for a breakout scenario
    mock_market_data = {
        "latest_close": 3280.80, 
        "20_day_high": 3271.60,
        "ema20": 3188.45, 
        "ema50": 3133.12, 
        "rsi": 73.90
    }
    
    async def main():
        try:
            analysis = await run_technical_agent("TCS.NS", mock_market_data)
            print("\n--- Live Agent Output ---")
            print(analysis.model_dump_json(indent=2))
        except Exception as e:
            print(f"Agent failed: {e}")

    asyncio.run(main())
