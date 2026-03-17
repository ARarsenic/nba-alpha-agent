import logging
import random
import os
import pytz
import requests
import json
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from nba_api.live.nba.endpoints import scoreboard

logger = logging.getLogger(__name__)

BLACKLIST_WORDS = ["series", "champion", "advance", "draft", "mvp", "rookie", "make playoffs"]
_polymarket_cache = None

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
    global _polymarket_cache
    match_name = match_dict["match_name"]
    logger.info(f"[{match_name}] Fetching market odds...")
    
    if _polymarket_cache is None:
        url = "https://gamma-api.polymarket.com/events"
        params = {"closed": "false", "active": "true", "tag_id": "745", "limit": 100}
        try:
            resp = requests.get(url, params=params, timeout=5)
            resp.raise_for_status()
            _polymarket_cache = resp.json()
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
                        # timezone naive vs UTC
                        end_date_utc = datetime.strptime(end_date_str, "%Y-%m-%dT%H:%M:%SZ")
                        now_utc = datetime.utcnow()
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
def _fetch_underdog_lineups() -> dict:
    url = "https://api.selanet.ai/v1/browse"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ.get('SELANET_API_KEY', 'YOUR_API_KEY_HERE')}"
    }
    payload = {
        "parse_only": True,
        "x_params": {"feature": "profile", "username": "UnderdogNBA", "tab":"tweets"}
    }
    lineups_dict = {}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        contents = resp.json().get("content", [])
        for item in contents:
            if item.get("content_type") == "tweet":
                text = item.get("fields", {}).get("text", "")
                if text.startswith("Lineup alert:"):
                    match = re.search(r"Lineup alert: (.*?) (?:will start|list starters as) (.*?) on", text)
                    if match:
                        team_name = match.group(1).strip()
                        players = [p.strip() for p in match.group(2).strip().split(',')]
                        abbr = TEAM_MAPPING.get(team_name, team_name)
                        lineups_dict[abbr] = players
    except Exception as e:
        logger.error(f"Underdog Lineup Fetch Error: {e}")
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
    COOKIE = "sessionid=wjkiiql5mzglpf585mxv4irn2t6asrz1"
    headers = {"User-Agent": "Mozilla/5.0", "Cookie": COOKIE}
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
    COOKIE = "sessionid=wjkiiql5mzglpf585mxv4irn2t6asrz1"
    headers = {"User-Agent": "Mozilla/5.0", "Cookie": COOKIE}
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
        _lineups_cache = _fetch_underdog_lineups()
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

if __name__ == "__main__":
    print(get_market_odds({'game_id': 'xxxxxxx', 'home_team': 'Minnesota Timberwolves', 'home_team_abbr': 'MIN', 'away_team': 'Phoenix Suns', 'away_team_abbr': 'PHX', 'status': 'unstart', 'match_name': 'PHX vs MIN'}))  
    print(json.dumps(get_nba_intelligence('PHX vs MIN', '2026-03-17'), indent=2))