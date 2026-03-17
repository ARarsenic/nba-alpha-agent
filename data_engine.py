import logging
import os
import pytz
import requests
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from nba_api.live.nba.endpoints import scoreboard

logger = logging.getLogger(__name__)

BLACKLIST_WORDS = ["series", "champion", "advance", "draft", "mvp", "rookie", "make playoffs"]
_polymarket_cache = None
_polymarket_cache_date = None  # Invalidate cache daily

# Cleaning the Glass session ID from environment variable (never hardcode)
_CTG_COOKIE = f"sessionid={os.getenv('CTG_SESSION_ID', '')}"

# Mapping from Mascot/Nickname to NBA Team Abbreviation
# Mapping from Mascot/Nickname/City to NBA Team Abbreviation
TEAM_MAPPING = {
    "Hawks": "ATL", "Atlanta": "ATL",
    "Celtics": "BOS", "Boston": "BOS",
    "Nets": "BKN", "Brooklyn": "BKN",
    "Hornets": "CHA", "Charlotte": "CHA",
    "Bulls": "CHI", "Chicago": "CHI",
    "Cavaliers": "CLE", "Cleveland": "CLE",
    "Mavericks": "DAL", "Dallas": "DAL", "Mavs": "DAL",
    "Nuggets": "DEN", "Denver": "DEN",
    "Pistons": "DET", "Detroit": "DET",
    "Warriors": "GSW", "Golden State": "GSW",
    "Rockets": "HOU", "Houston": "HOU",
    "Pacers": "IND", "Indiana": "IND",
    "Clippers": "LAC", "LA": "LAC", "L.A. Clippers": "LAC",
    "Lakers": "LAL", "Los Angeles": "LAL", "L.A. Lakers": "LAL",
    "Grizzlies": "MEM", "Memphis": "MEM",
    "Heat": "MIA", "Miami": "MIA",
    "Bucks": "MIL", "Milwaukee": "MIL",
    "Timberwolves": "MIN", "Minnesota": "MIN",
    "Pelicans": "NOP", "New Orleans": "NOP",
    "Knicks": "NYK", "New York": "NYK",
    "Thunder": "OKC", "Oklahoma City": "OKC",
    "Magic": "ORL", "Orlando": "ORL",
    "76ers": "PHI", "Philadelphia": "PHI",
    "Suns": "PHX", "Phoenix": "PHX",
    "Trail Blazers": "POR", "Portland": "POR",
    "Kings": "SAC", "Sacramento": "SAC",
    "Spurs": "SAS", "San Antonio": "SAS",
    "Raptors": "TOR", "Toronto": "TOR",
    "Jazz": "UTA", "Utah": "UTA",
    "Wizards": "WAS", "Washington": "WAS"
}

def _make_soup(html):
    try:
        return BeautifulSoup(html, "lxml")
    except:
        return BeautifulSoup(html, "html.parser")

def get_todays_matches() -> list:
    """
    Stage 1: Daily Setup - Get today's matches using NBA API live endpoints.
    """
    tz_ny = pytz.timezone('America/New_York')
    target_date = datetime.now(tz_ny).strftime('%Y-%m-%d')
    logger.info(f"Fetching {target_date} (EST) matches from NBA API...")
    
    try:
        board = scoreboard.ScoreBoard()
        games = board.games.get_dict()
        match_list = []
        
        for game in games:
            game_id = game['gameId']
            game_status = game['gameStatusText']
            home_team = game['homeTeam']
            away_team = game['awayTeam']

            match_info = {
                "game_id": game_id,
                "home_team": f"{home_team['teamCity']} {home_team['teamName']}",
                "home_team_abbr": home_team['teamTricode'],
                "away_team": f"{away_team['teamCity']} {away_team['teamName']}",
                "away_team_abbr": away_team['teamTricode'],
                "status": game_status,
                "match_name": f"{away_team['teamTricode']} vs {home_team['teamTricode']}"
            }
            match_list.append(match_info)
            
        logger.info(f"Found {len(match_list)} matches today.")
        return match_list
    except Exception as e:
        logger.error(f"Failed to fetch today's matches: {e}")
        return []

def get_market_odds(match_dict: dict) -> dict:
    """
    Stage 2: Market Data - Polymarket Gamma API.
    """
    global _polymarket_cache, _polymarket_cache_date
    match_name = match_dict["match_name"]
    logger.info(f"[{match_name}] Fetching market odds...")

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if _polymarket_cache is None or _polymarket_cache_date != today:
        url = "https://gamma-api.polymarket.com/events"
        params = {"closed": "false", "active": "true", "tag_id": "745", "limit": 100}
        try:
            resp = requests.get(url, params=params, timeout=5)
            resp.raise_for_status()
            _polymarket_cache = resp.json()
            _polymarket_cache_date = today
        except Exception as e:
            logger.error(f"Polymarket API Error: {e}")
            _polymarket_cache = []

    home_short = match_dict["home_team"].split(" ")[-1]
    away_short = match_dict["away_team"].split(" ")[-1]
    
    for event in _polymarket_cache:
        title = event.get("title", "").lower()
        
        if any(word in title for word in BLACKLIST_WORDS):
            continue 
            
        if home_short.lower() in title and away_short.lower() in title:
            markets = event.get("markets", [])
            for market in markets:
                outcomes_str = market.get("outcomes", "[]")
                prices_str = market.get("outcomePrices", "[]")
                
                outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
                prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
                
                if len(outcomes) == 2 and (home_short in outcomes[0] or home_short in outcomes[1]):
                    end_date_str = market.get("endDate", "")
                    if end_date_str:
                        end_date_utc = datetime.strptime(end_date_str, "%Y-%m-%dT%H:%M:%SZ")
                        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                        if (end_date_utc - now_utc) > timedelta(days=3):
                            continue
                    
                    return {
                        "match_name": match_name,
                        "condition_id": market.get("conditionId"),
                        "yes_price": float(prices[0]),
                        "no_price": float(prices[1]),
                        "yes_team": outcomes[0],
                        "no_team": outcomes[1],
                        "liquidity": float(market.get("liquidity", 0))
                    }
                    
    logger.warning(f"[{match_name}] Polymarket odds not found.")
    return {}

# ==========================================
# Intelligence Scraper Helpers
# ==========================================
def _fetch_fantasydata_lineups(target_date: str) -> dict:
    url = f"https://fantasydata.com/nba/starting-lineups?date={target_date}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    lineups_dict = {}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = _make_soup(resp.text)
        
        games = soup.find_all("div", class_=lambda c: c and "game" in c.lower())
        for game in games:
            header = game.find("div", class_="header")
            if not header: continue
            
            match_text = header.get_text(separator=' ', strip=True) 
            split_at = match_text.split('@')
            if len(split_at) < 2: continue
            
            away_team_name = split_at[0].strip()
            home_part = split_at[1]
            
            # Extract home team name by removing the time (e.g. "Hornets 7:00 PM")
            time_match = re.search(r'\d{1,2}:\d{2}\s*[AP]M', home_part)
            if time_match:
                home_team_name = home_part[:time_match.start()].strip()
            else:
                home_team_name = home_part.split()[0].strip()

            lineup_div = game.find("div", class_="lineup")
            if not lineup_div: continue
            
            def get_players(side):
                side_div = lineup_div.find("div", class_=side)
                if not side_div: return []
                players = []
                for p_div in side_div.find_all("div", class_="text-nowrap"):
                    # Stop once we hit the "Injuries" section header
                    strong = p_div.find("strong")
                    if strong and "injuries" in strong.get_text(strip=True).lower():
                        break
                    a_tag = p_div.find("a")
                    if a_tag:
                        p_name = a_tag.get_text(strip=True)
                        if p_name: players.append(p_name)
                return players
            
            away_abbr = TEAM_MAPPING.get(away_team_name, away_team_name)
            home_abbr = TEAM_MAPPING.get(home_team_name, home_team_name)
            
            away_players = get_players("away")
            home_players = get_players("home")
            
            lineups_dict[away_abbr] = away_players
            lineups_dict[home_abbr] = home_players
            
    except Exception as e:
        logger.error(f"FantasyData Lineup Fetch Error: {e}")
    return lineups_dict

def _fetch_cbs_injuries() -> dict:
    base_url = 'https://www.cbssports.com'
    injuries_url = f'{base_url}/nba/injuries/'
    league_report = {}
    try:
        res = requests.get(injuries_url, timeout=10)
        soup = _make_soup(res.text)
        injury_table = soup.find('div', class_='Page-colMain')
        if not injury_table:
            return {}
        teams = injury_table.find_all('div', id='TableBase')
        for team in teams:
            team_name = team.find('span', class_='TeamName').string
            abbr = TEAM_MAPPING.get(team_name, team_name)
            
            team_injuries = []
            table = team.find('table', class_='TableBase-table')
            if table:
                headers = [th.string for th in table.find_all('th')]
                players = table.find('tbody').find_all('tr')
                for player in players:
                    p_data = {}
                    for h, d in zip(headers, player.find_all('td')):
                        h_strip = h.strip()
                        if h_strip == "Player":
                            if d.contents and d.contents[-1].string:
                                p_data[h_strip] = d.contents[-1].string.strip()
                            else:
                                p_data[h_strip] = d.get_text(separator=" ", strip=True)
                        else:
                            p_data[h_strip] = d.get_text(separator=" ", strip=True)
                    team_injuries.append(p_data)
                    
            clean_injuries = []
            for inj in team_injuries:
                clean_injuries.append({
                    "player": inj.get("Player", "Unknown"),
                    "status": inj.get("Injury Status", inj.get("Status", "Unknown")),
                    "reason": inj.get("Injury", "Unknown"),
                    "impact_level": "UNKNOWN" # Placeholder, LLM or logic can refine this
                })
            league_report[abbr] = clean_injuries
    except Exception as e:
        logger.error(f"CBS Injury Fetch Error: {e}")
    return league_report

def _fetch_cleaning_the_glass(target_date: str) -> list:
    BASE = "https://www.cleaningtheglass.com"
    headers = {"User-Agent": "Mozilla/5.0", "Cookie": _CTG_COOKIE}
    url = f"{BASE}/stats/games?date={target_date}"
    all_games = []
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        soup = _make_soup(resp.text)
        game_cards = soup.find_all("div", class_="card game")
        for card in game_cards:
            table = card.find("table", class_="unplayed")
            if not table: continue
            tbody = table.find("tbody")
            if not tbody: continue
            
            teams_data = []
            preview_url = None
            for row in tbody.find_all("tr"):
                team_td = row.find("td", class_="team_name")
                if team_td:
                    team_name = team_td.get_text(strip=True)
                    stats = row.find_all("td", class_="stat")
                    if len(stats) >= 7:
                        teams_data.append({
                            "team": team_name,
                            "days_rest": stats[0].get_text(strip=True),
                            "record": {
                                "overall": f"{stats[1].get_text(strip=True)}-{stats[2].get_text(strip=True)}",
                                "home": f"{stats[3].get_text(strip=True)}-{stats[4].get_text(strip=True)}",
                                "away": f"{stats[5].get_text(strip=True)}-{stats[6].get_text(strip=True)}"
                            }
                        })
                period_td = row.find("td", class_="period_string")
                if period_td:
                    a_tag = period_td.find("a", href=True)
                    if a_tag and "game_preview" in a_tag["href"]:
                        preview_url = urljoin(BASE, a_tag["href"])
            if teams_data and preview_url:
                all_games.append({"teams": teams_data, "preview_url": preview_url})
    except Exception as e:
        logger.error(f"CleaningTheGlass Fetch Error: {e}")
    return all_games

def _extract_preview_tables(soup, title_keyword):
    h2 = soup.find("h2", string=lambda x: x and title_keyword in x)
    if not h2: return {}
    section = h2.find_parent("div", class_="content_section")
    data = {}
    if section:
        tables = section.find_all("table", class_="stat_table")
        for table in tables:
            # 1) Parse headers dynamically
            thead = table.find("thead")
            header_names = []
            if thead:
                header_rows = thead.find_all("tr")
                if header_rows:
                    last_header_row = header_rows[-1]
                    for th in last_header_row.find_all("th"):
                        txt = th.get_text(separator=" ", strip=True)
                        if txt:  # Skip empty headers
                            header_names.append(txt)

            # 2) Parse data rows
            tbody = table.find("tbody")
            rows = tbody.find_all("tr") if tbody else table.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if not cells:
                    continue
                team = cells[0].get_text(strip=True)
                # Ignore spacer rows
                if not team and 'spacer' in cells[0].get('class', []):
                    continue
                
                if team:
                    val_cells = [v for v in cells[1:] if 'spacer' not in v.get('class', [])]
                    
                    # If columns align nicely with headers (2 cells for every 1 header: Rank/Value)
                    if header_names and len(val_cells) == len(header_names) * 2:
                        team_data = {}
                        for i, h_name in enumerate(header_names):
                            # Deduplicate header names if they appear twice (e.g. Pts/Play)
                            unique_h = h_name
                            counter = 1
                            while unique_h in team_data:
                                counter += 1
                                unique_h = f"{h_name}_{counter}"
                                
                            rank = val_cells[i*2].get_text(strip=True)
                            val = val_cells[i*2 + 1].get_text(strip=True)
                            team_data[unique_h] = {"value": val, "rank": rank}
                        data[team] = team_data
                    else:
                        # Fallback to flat list
                        data[team] = [v.get_text(strip=True) for v in val_cells]
    return data

def _fetch_game_preview_stats(url: str) -> dict:
    headers = {"User-Agent": "Mozilla/5.0", "Cookie": _CTG_COOKIE}
    results = {}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        soup = _make_soup(resp.text)
        
        results["four_factors"] = _extract_preview_tables(soup, "Four Factors")
        results["shooting_frequency"] = _extract_preview_tables(soup, "Shooting: Frequency")
        results["shooting_accuracy"] = _extract_preview_tables(soup, "Shooting: Accuracy")
        results["halfcourt_putbacks"] = _extract_preview_tables(soup, "Halfcourt and Putbacks")
        results["transition"] = _extract_preview_tables(soup, "Transition")

    except Exception as e:
        logger.error(f"Game Preview Fetch Error for {url}: {e}")
    return results

# Global caches to avoid spamming the APIs for every single match
_injuries_cache = None
_lineups_cache = None
_ctg_games_cache = None
_last_scrape_date = None

def get_nba_intelligence(match_name: str, match_date: str = None) -> dict:
    """
    Stage 2: Hardcore/Slow/Fast Data - Integrated MBA API Intelligence.
    Returns:
    {
      "date": "2026-03-xx",
      "matchup": "LAL vs DEN",
      "Lineup":  {"LAL" : [...], "DEN": [...]},
      "injury_impact": {"LAL": [...], "DEN": [...]},
      "days_rest": {"LAL": "1", "DEN": "2"},
      "record": {"LAL": {"overall":...}, "DEN": {"overall":...}},
      
    }
    """
    global _injuries_cache, _lineups_cache, _ctg_games_cache, _last_scrape_date
    
    logger.info(f"[{match_name}] Fetching NBA intelligence...")
    
    # 1) Parse teams
    try:
        away_abbr, home_abbr = match_name.split(" vs ")
    except ValueError:
        logger.error(f"Invalid match_name format: {match_name}. Expected 'AWAY vs HOME'")
        return {}

    # 2) Date handling
    if not match_date:
        tz_ny = pytz.timezone('America/New_York')
        match_date = datetime.now(tz_ny).strftime('%Y-%m-%d')
        
    # Refresh caches if date changed or first run
    if _last_scrape_date != match_date:
        logger.info(f"Building intelligence cache for {match_date}...")
        _injuries_cache = _fetch_cbs_injuries()
        _lineups_cache = _fetch_fantasydata_lineups(match_date)
        _ctg_games_cache = _fetch_cleaning_the_glass(match_date)
        _last_scrape_date = match_date

    # 3) Build Final Dict
    nba_intel = {
        "date": match_date,
        "matchup": match_name,
        "Lineup": {
            home_abbr: _lineups_cache.get(home_abbr, []),
            away_abbr: _lineups_cache.get(away_abbr, [])
        },
        "injury_impact": {
            home_abbr: _injuries_cache.get(home_abbr, []),
            away_abbr: _injuries_cache.get(away_abbr, [])
        },
        "days_rest": {},
        "record": {},
        "preview_url": None
    }

    # Extract team-specific CTG data
    for game in _ctg_games_cache:
        teams = game.get("teams", [])
        team_abbrs = [t.get("team") for t in teams]
        if home_abbr in team_abbrs and away_abbr in team_abbrs:
            nba_intel["preview_url"] = game.get("preview_url")
            for t_data in teams:
                t_name = t_data["team"]
                nba_intel["days_rest"][t_name] = t_data.get("days_rest")
                nba_intel["record"][t_name] = t_data.get("record")
            break
            
    # 4) Fetch Preview Detailed Stats
    if nba_intel.get("preview_url"):
        logger.info(f"[{match_name}] Fetching detailed preview stats...")
        preview_stats = _fetch_game_preview_stats(nba_intel["preview_url"])
        nba_intel.update(preview_stats)
    else:
        # Fill empty if missing
        for key in ["four_factors", "shooting_frequency", "shooting_accuracy", "halfcourt_putbacks", "transition"]:
            nba_intel[key] = {}

    # Removing preview_url from the final dictionary
    if "preview_url" in nba_intel:
        del nba_intel["preview_url"]

    return nba_intel

def get_game_result(match_name: str, pm_condition_id: str, trade_side: str) -> dict:
    """
    Stage 5: Settlement - Determine the real outcome of a finished NBA game.

    Strategy:
      1. Primary: NBA live scoreboard (nba_api) — look for the game by team abbr
         and read the final score. The team with more points wins.
      2. Secondary: Polymarket market price — if the condition_id is known and the
         market is resolved (price == 1.0 or 0.0), use that as ground truth.
      3. Fallback: return {"status": "PENDING"} so the trade stays open.

    Returns dict with keys:
      status   : "WIN" | "LOSS" | "PENDING"
      method   : which source was used
      details  : human-readable reason string
    """
    try:
        away_abbr, home_abbr = match_name.split(" vs ")
    except ValueError:
        return {"status": "PENDING", "method": "error", "details": f"Invalid match_name: {match_name}"}

    # ------------------------------------------------------------------ #
    # 1) NBA API — live scoreboard                                          #
    # ------------------------------------------------------------------ #
    try:
        board = scoreboard.ScoreBoard()
        games = board.games.get_dict()
        for game in games:
            h = game["homeTeam"]["teamTricode"]
            a = game["awayTeam"]["teamTricode"]
            if {h, a} != {home_abbr, away_abbr}:
                continue

            status_text = game.get("gameStatusText", "").lower()
            # Only settle if game is truly final
            if "final" not in status_text:
                return {
                    "status": "PENDING",
                    "method": "nba_api",
                    "details": f"Game still in progress: {status_text}"
                }

            home_score = int(game["homeTeam"].get("score", 0))
            away_score = int(game["awayTeam"].get("score", 0))

            if home_score == away_score:
                return {"status": "PENDING", "method": "nba_api", "details": "Tied — waiting for OT resolution"}

            winner_abbr = home_abbr if home_score > away_score else away_abbr
            # trade_side may be a full team name from Polymarket (e.g. "Minnesota Timberwolves")
            # winner_abbr is a tricode (e.g. "MIN") — use substring matching in both directions
            ts = trade_side.upper()
            wa = winner_abbr.upper()
            is_win = (ts == wa or ts in wa or wa in ts or
                      home_abbr.upper() in ts or away_abbr.upper() in ts and wa == away_abbr.upper())
            return {
                "status": "WIN" if is_win else "LOSS",
                "method": "nba_api",
                "details": (
                    f"{home_abbr} {home_score} - {away_abbr} {away_score}; "
                    f"winner={winner_abbr}; bet_on={trade_side}"
                )
            }

        logger.info(f"[{match_name}] Not found in today's NBA scoreboard — trying Polymarket...")
    except Exception as e:
        logger.warning(f"[{match_name}] NBA API error during settlement: {e}")

    # ------------------------------------------------------------------ #
    # 2) Polymarket — check resolved market price                           #
    # ------------------------------------------------------------------ #
    if pm_condition_id:
        try:
            url = "https://gamma-api.polymarket.com/markets"
            params = {"conditionId": pm_condition_id}
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                market = data[0]
                outcomes_raw = market.get("outcomes", "[]")
                prices_raw = market.get("outcomePrices", "[]")
                outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
                prices = [float(p) for p in (json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw)]

                # Resolved market: one price == 1.0
                for outcome, price in zip(outcomes, prices):
                    if price >= 0.99:  # effectively settled to 1
                        winning_team = outcome
                        is_win = (trade_side.upper() in winning_team.upper() or
                                  winning_team.upper() in trade_side.upper())
                        return {
                            "status": "WIN" if is_win else "LOSS",
                            "method": "polymarket",
                            "details": f"Polymarket resolved: {winning_team} won (price={price}); bet_on={trade_side}"
                        }

                logger.info(f"[{match_name}] Polymarket market not yet resolved.")
        except Exception as e:
            logger.warning(f"[{match_name}] Polymarket settlement check error: {e}")

    # ------------------------------------------------------------------ #
    # 3) Fallback — cannot settle yet                                       #
    # ------------------------------------------------------------------ #
    return {
        "status": "PENDING",
        "method": "none",
        "details": "Could not determine result from NBA API or Polymarket"
    }


if __name__ == "__main__":
    print(get_market_odds({'game_id': 'xxxxxxx', 'home_team': 'Minnesota Timberwolves', 'home_team_abbr': 'MIN', 'away_team': 'Phoenix Suns', 'away_team_abbr': 'PHX', 'status': 'unstart', 'match_name': 'PHX vs MIN'}))  
    print(json.dumps(get_nba_intelligence('PHX vs MIN', '2026-03-17'), indent=2))
    print(get_game_result('ORL vs ATL', 'xxxxxxx', 'ATL'))