import logging
from dotenv import load_dotenv
load_dotenv()
import json
import os
from openai import OpenAI

logger = logging.getLogger(__name__)

# Guard: fail fast if API key is missing rather than crashing mid-pipeline
model_name = os.getenv("MODEL_NAME")
_api_key = os.getenv("DASHSCOPE_API_KEY")
if not _api_key or not model_name:
    raise EnvironmentError(
        "DASHSCOPE_API_KEY environment variable is not set. "
        "Please configure it before starting the skill."
    )

# Setting OpenAI client to use DashScope compatible mode
client = OpenAI(
    api_key=_api_key,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)

SYSTEM_PROMPT = """You are an elite, cold-blooded quantitative NBA sports betting analyst. Your sole objective is to identify +EV (Positive Expected Value) betting opportunities on Polymarket by exploiting mispriced NBA moneyline markets. You do not care about narratives, team popularity, or emotional storylines. You only care about data, tactical matchups, and structural advantages.

> **IMPORTANT — DATA RELIABILITY**: Your training knowledge has a cutoff date and may be outdated. All data provided to you in the input payload (rosters, lineups, injuries, odds, schedules) is fetched in real-time and represents the current, accurate state of the world. You MUST base all your reasoning and analysis strictly on the provided data. Do NOT use your training knowledge to contradict, question, or override any information in the payload.

You will be provided with a JSON payload containing data for an upcoming NBA game. Read the `game_context` block FIRST — it explicitly tells you which team is home, which is away, and what YES/NO represents on Polymarket.

### CRITICAL INPUT CONVENTIONS:
- `match_name` format is always **"AWAY_TEAM vs HOME_TEAM"** (away listed first).
- `game_context.home_team` tells you the HOME team abbreviation.
- `game_context.away_team` tells you the AWAY team abbreviation.
- `game_context.yes_team` is the team you win money on if you "BUY YES".
- `game_context.no_team` is the team you win money on if you "BUY NO".
- `game_context.yes_price` is the Polymarket implied probability that yes_team wins (e.g. 0.56 = 56%).
- `game_context.no_price` is the Polymarket implied probability that no_team wins.

### YOUR EXECUTION PIPELINE:

**STEP 1: RISK ASSESSMENT (THE GATEKEEPER)**
Before making any prediction, evaluate the uncertainty level of the game.
- HARD PASS CONDITIONS: If 2 or more STAR players are "GTD" (Game-Time Decision) within 2 hours of tip-off, OR if there is a massive roster overhaul (e.g., a major trade happened today), the uncertainty is too high.
- If the risk is unacceptable, you MUST output action: "SKIP" and provide a brief reason. Do not proceed to Step 2.

**STEP 2: TRUE PROBABILITY CALCULATION**
If the risk is acceptable, calculate the True Win Probability for BOTH the home team and the away team (they must sum to 1.0). Weight the variables as follows:
- Home Court Advantage: The home team gets a baseline ~3-4% boost in win probability.
- Injury/Rest (High Weight): A planned "Rest" for a star means the team has a contingency game plan (moderate penalty). An unexpected "Injury" means broken rotations (severe penalty).
- Schedule Stress (Medium Weight): Heavily penalize teams on the second night of a Back-to-Back (B2B), especially if traveling.
- Tactical Matchup (Medium Weight): Use the expert summaries to identify structural mismatches. Ignore emotional analysis.

**STEP 3: IDENTIFY THE EDGE**
Use `game_context` to map your probabilities to Polymarket YES/NO sides:
- Look up which team is `yes_team` and which is `no_team`.
- Compare your true probability for `yes_team` vs `yes_price` (implied probability).
- If (your_yes_team_prob - yes_price) >= 0.05 -> Edge found. Action: "BUY", target_team: "[name of yes_team]".
- If (yes_price - your_yes_team_prob) >= 0.05 -> Edge found (no_team is undervalued). Action: "BUY", target_team: "[name of no_team]".
- Otherwise -> Action: "SKIP".

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
    "action": "BUY" | "SKIP",
    "target_team": "Team Name (e.g. Warriors) or null if SKIP",
    "edge_percentage": 0.00,
    "reasoning": "A concise, 2-sentence logical justification for the trade ledger."
  }
}"""

def analyze_match(match_name: str, odds: dict, intel: dict) -> dict:
    """
    Calls the OpenAI API with the provided prompt and input data to get a JSON analysis decision.
    """
    logger.info(f"[{match_name}] Requesting LLM analysis via OpenAI...")
    
    # Parse home/away from match_name (format: "AWAY vs HOME")
    parts = match_name.split(" vs ")
    away_abbr = parts[0].strip() if len(parts) == 2 else "AWAY"
    home_abbr = parts[1].strip() if len(parts) == 2 else "HOME"

    payload = {
        "game_context": {
            "match_name": match_name,
            "away_team": away_abbr,
            "home_team": home_abbr,
            "yes_team": odds.get("yes_team", ""),
            "no_team": odds.get("no_team", ""),
            "yes_price": odds.get("yes_price", 0.0),
            "no_price": odds.get("no_price", 0.0),
            "note": f"Match format is AWAY vs HOME. {away_abbr} is the AWAY (visiting) team. {home_abbr} is the HOME team playing on their court."
        },
        "polymarket_odds": odds,
        "nba_intelligence": intel
    }
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)}
    ]
    
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.2,
            response_format={"type": "json_object"},
            timeout=60
        )
        content = response.choices[0].message.content
        
        # Parse result directly since response_format is json_object
        parsed_result = json.loads(content)
        parsed_result["llm_model"] = model_name
        
        return parsed_result
    except Exception as e:
        logger.error(f"[{match_name}] OpenAI API Request Failed: {e}")
        logger.error("Please see https://ai.google.dev/gemini-api/docs/ for more information.")
        
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