import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data.json"

URL = "https://www.espn.com/golf/leaderboard/_/tournamentId/401811942"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
}

SPECIAL_SCORES = {"CUT", "WD", "DQ", "MDF"}


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def load_existing():
    if DATA_PATH.exists():
        try:
            return json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def normalize_score(score):
    s = clean_text(score).upper()
    if not s:
        return ""
    if s == "0":
        return "E"
    if s == "E":
        return "E"
    if s in SPECIAL_SCORES:
        return s
    return s


def normalize_thru(thru):
    s = clean_text(thru).upper()
    if not s:
        return "-"
    if s in {"FINAL", "FIN"}:
        return "F"
    return s


def score_sort_value(score):
    s = normalize_score(score)
    if s in SPECIAL_SCORES:
        return 9000
    if s == "E":
        return 0
    try:
        return int(s)
    except Exception:
        return 9999


def pos_sort_value(pos):
    s = clean_text(pos).upper().replace("T", "")
    try:
        return int(s)
    except Exception:
        return 9999


def parse_espn(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [clean_text(x) for x in text.splitlines() if clean_text(x)]

    players = []
    seen = set()
    in_board = False

    row_pattern = re.compile(
        r'^(?P<pos>T?\d+)'                       # position
        r'(?:\s+\d+|-)?'                        # optional movement or dash
        r'【\d+†Image:[^】]+】'                   # flag image token
        r'【\d+†(?P<name>[^】]+)】'               # player name token
        r'(?P<score>[+-]?\d+|E|CUT|WD|DQ|MDF)'  # score
        r'(?P<today>[+-]?\d+|E|-)\s+'           # today
        r'(?P<thru>F|\d+\*?)\b',                # thru
        re.IGNORECASE,
    )

    for line in lines:
        upper = line.upper()

        if "POS PLAYER SCORE TODAY THRU" in upper:
            in_board = True
            continue

        if not in_board:
            continue

        if upper.startswith("ADVERTISEMENT") or upper.startswith("ESPN BET"):
            break

        m = row_pattern.match(line)
        if not m:
            continue

        name = clean_text(m.group("name"))
        if len(name.split()) < 2:
            continue

        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        players.append(
            {
                "pos": clean_text(m.group("pos")).upper(),
                "name": name,
                "score": normalize_score(m.group("score")),
                "thru": normalize_thru(m.group("thru")),
            }
        )

    return players


def fetch_html():
    resp = requests.get(URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def build_output(players, note):
    players = sorted(
        players,
        key=lambda p: (
            score_sort_value(p.get("score")),
            pos_sort_value(p.get("pos")),
            p.get("name", ""),
        ),
    )
    return {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "source_name": "ESPN RBC Heritage leaderboard",
        "source_url": URL,
        "note": note,
        "players": players,
    }


def main():
    existing = load_existing()

    try:
        html = fetch_html()
        players = parse_espn(html)

        if players:
            output = build_output(players, f"Parsed {len(players)} players successfully.")
            DATA_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
            print(f"Updated data.json with {len(players)} players")
            return
        else:
            print("Parser found 0 players")

    except Exception as e:
        print(f"Failed to fetch/parse ESPN page: {e}")

    if existing:
        existing["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        existing["note"] = "Refresh failed; kept last good data."
        DATA_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        print("Kept existing data.json because refresh failed")
    else:
        fallback = build_output([], "Refresh failed and there was no previous data.")
        DATA_PATH.write_text(json.dumps(fallback, indent=2), encoding="utf-8")
        print("Wrote empty fallback data.json")


if __name__ == "__main__":
    main()
