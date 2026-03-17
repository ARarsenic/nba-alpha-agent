import logging
import json
import os
from openai import OpenAI

logger = logging.getLogger(__name__)

# Guard: fail fast if API key is missing rather than crashing mid-pipeline
_api_key = os.getenv("DASHSCOPE_API_KEY")
if not _api_key:
    raise EnvironmentError(
        "DASHSCOPE_API_KEY environment variable is not set. "
        "Please configure it before starting the skill."
    )

# Setting OpenAI client to use DashScope compatible mode
client = OpenAI(
    api_key=_api_key,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

SYSTEM_PROMPT = """You are an elite, cold-blooded quantitative NBA sports betting analyst. Your sole objective is to identify +EV (Positive Expected Value) betting opportunities on Polymarket by exploiting mispriced NBA moneyline markets. You do not care about narratives, team popularity, or emotional storylines. You only care about data, tactical matchups, and structural advantages.

You will be provided with a JSON payload containing data for an upcoming NBA game, including:
1. Polymarket Implied Odds
2. Schedule Context (e.g., Back-to-Back fatigue)
3. Injury/Roster Updates (Distinguishing between planned 'Rest' and unexpected 'Injury')
4. Filtered Tactical Expert Summaries

### YOUR EXECUTION PIPELINE:

**STEP 1: RISK ASSESSMENT (THE GATEKEEPER)**
Before making any prediction, evaluate the uncertainty level of the game.
- HARD PASS CONDITIONS: If 2 or more STAR players are "GTD" (Game-Time Decision) within 2 hours of tip-off, OR if there is a massive roster overhaul (e.g., a major trade happened today), the uncertainty is too high. 
- If the risk is unacceptable, you MUST output action: "SKIP" and provide a brief reason. Do not proceed to Step 2.

**STEP 2: TRUE PROBABILITY CALCULATION**
If the risk is acceptable, calculate the "True Win Probability" for the HOME team. Weight the variables as follows:
- Injury/Rest (High Weight): A planned "Rest" for a star means the team has a contingency game plan (moderate penalty). An unexpected "Injury" means broken rotations (severe penalty).
- Schedule Stress (Medium Weight): Heavily penalize teams on the second night of a Back-to-Back (B2B), especially if traveling.
- Tactical Matchup (Medium Weight): Use the expert summaries to identify structural mismatches (e.g., Team A allows the most 3PT attempts, Team B shoots the most 3PTs). Ignore any emotional analysis in the summary.

**STEP 3: IDENTIFY THE EDGE**
Compare your calculated "True Probability" against the "Polymarket Implied Probability".
- If (True Probability - Implied Probability) >= 0.05 -> Edge found. Recommendation: "BUY YES".
- If (Implied Probability - True Probability) >= 0.05 -> Edge found. Recommendation: "BUY NO".
- Otherwise -> "SKIP" (No edge).

### OUTPUT FORMAT (STRICT JSON ONLY)
You must output your final decision in valid JSON format. Do NOT wrap the JSON in markdown code blocks. Do NOT output any conversational text. Use the following schema:

{
  "risk_assessment": {
    "status": "PASS" | "FAIL",
    "uncertainty_level": "LOW" | "MEDIUM" | "HIGH",
    "risk_notes": "Brief explanation of the risk evaluation."
  },
  "analysis": {
    "home_true_probability": 0.00,
    "away_true_probability": 0.00,
    "key_factors": ["Factor 1", "Factor 2"]
  },
  "decision": {
    "action": "BUY YES" | "BUY NO" | "SKIP",
    "edge_percentage": 0.00,
    "reasoning": "A concise, 2-sentence logical justification for the trade ledger."
  }
}"""

def analyze_match(match_name: str, odds: dict, intel: dict) -> dict:
    """
    Calls the OpenAI API with the provided prompt and input data to get a JSON analysis decision.
    """
    logger.info(f"[{match_name}] Requesting LLM analysis via OpenAI...")
    
    payload = {
        "polymarket_odds": odds,
        "nba_intelligence": intel
    }
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)}
    ]
    
    try:
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=messages,
            temperature=0.2,
            response_format={"type": "json_object"},
            timeout=60
        )
        content = response.choices[0].message.content
        
        # Parse result directly since response_format is json_object
        parsed_result = json.loads(content)
        parsed_result["llm_model"] = "qwen-plus"
        
        return parsed_result
    except Exception as e:
        logger.error(f"[{match_name}] OpenAI API Request Failed: {e}")
        logger.error("请参考文档：https://www.alibabacloud.com/help/model-studio/developer-reference/error-code")
        
        # Return a safe fallback to prevent downstream crashes
        return {
            "risk_assessment": {
                "status": "FAIL",
                "uncertainty_level": "HIGH",
                "risk_notes": f"LLM parsing or API execution failed: {e}"
            },
            "decision": {
                "action": "SKIP",
                "reasoning": "System error preventing analysis."
            }
        }
