from backend.config.app_config import get_app_config
import os
import json
import asyncio
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from groq import AsyncGroq

load_dotenv()

class RiskAssessment(BaseModel):
    symbol: str = Field(description="Asset ticker symbol")
    risk_level: str = Field(description="LOW, MEDIUM, or HIGH")
    max_position_size_pct: float = Field(description="Recommended max portfolio allocation percentage (1.0 to 15.0)")
    stop_loss_pct: float = Field(description="Suggested stop-loss percentage below entry")
    risk_summary: str = Field(description="Concise 1-sentence risk summary")

async def run_risk_agent(symbol: str, recent_data: dict, technical_score: float) -> RiskAssessment:
    """
    Evaluates volatility and technical score to output strict risk parameters asynchronously.
    """
    api_key = get_app_config().groq_api_key
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set in .env")
        
    client = AsyncGroq(api_key=api_key)
    schema_json = json.dumps(RiskAssessment.model_json_schema(), indent=2)
    
    prompt = f"""
    You are the Chief Risk Officer for an algorithmic trading desk.
    Review the following technical indicators and score for {symbol}:
    Indicators: {json.dumps(recent_data, indent=2)}
    Technical Conviction Score: {technical_score}/10.0
    
    Determine the risk level, maximum safe position sizing %, and stop-loss %.
    Output ONLY valid JSON matching this schema:
    {schema_json}
    """
    
    chat_completion = await client.chat.completions.create(
        messages=[
            {"role": "system", "content": "You are a specialized risk management AI that only outputs raw, valid JSON."},
            {"role": "user", "content": prompt}
        ],
        model="openai/gpt-oss-120b",
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    
    return RiskAssessment.model_validate_json(chat_completion.choices[0].message.content)

if __name__ == "__main__":
    print("Running Live Risk Agent via Groq...")
    mock_market_data = {
        "latest_close": 3280.80, 
        "20_day_high": 3271.60,
        "ema20": 3188.45, 
        "ema50": 3133.12, 
        "rsi": 73.90
    }
    
    async def main():
        try:
            assessment = await run_risk_agent("TCS.NS", mock_market_data, technical_score=8.5)
            print("\n--- Live Risk Output ---")
            print(assessment.model_dump_json(indent=2))
        except Exception as e:
            print(f"Risk Agent failed: {e}")

    asyncio.run(main())
