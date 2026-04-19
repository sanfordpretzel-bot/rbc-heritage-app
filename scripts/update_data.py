import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data.json"

PAGES = [
    {
        "name": "ESPN RBC Heritage leaderboard",
        "url": "https://www.espn.com/golf/leaderboard/_/tournamentId/401811942",
    }
]

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
}

SPECIAL_SCORES = {"CUT", "WD", "DQ", "MDF"}


def load_existing():
    if DATA_PATH.exists():
        try:
            return json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_score(score):
    score = clean_text(score).upper()
    if not score:
        return ""
    if score == "E":
        return "E"
    if score in SPECIAL_SCORES:
        return score
    if re.fullmatch(r"[+-]?\d+", score):
        n = int(score)
        return "E" if n == 0 else str(n)
    return score


def normalize_thru(thru):
    thru = clean_text(thru).upper()
    if not thru:
        return "-"
    if thru in {"F", "FIN", "FINAL"}:
        return "F"
    return thru


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

    start_idx = None
    for i, line in enumerate(lines):
        if "POS PLAYER SCORE TODAY THRU" in line.upper():
            start_idx = i + 1
            break

    if start_idx is None:
        return []

    for line in lines[start_idx:]:
        upper = line.upper()
        if upper.startswith("ADVERTISEMENT") or upper.startswith("ESPN BET") or upper.startswith("FULL LEADERBOARD"):
            break

        # Find player name inside the ESPN link token: 
        name_match = re.search(r'【\d+†([^】]+)】', line)
        if not name_match:
            continue

        name = clean_text(name_match.group(1))
        if len(name.split()) < 2:
            continue

        # Remove image links so we can parse around the name more easily
        line_no_images = re.sub(r'【\d+†Image:[^】]+】', '', line)

        # Position is at the very start, like:
        # 1-
        # 2 1
        # T4 15
        # T16-
        pos_match = re.match(r'^(T?\d+)', line_no_images)
        if not pos_match:
            continue
        pos = pos_match.group(1).upper()

        # After the player name, ESPN packs:
        # score + today + thru
        # examples:
        # -19-2 14
        # -13-4 F
        # -12 E 17
        # -6+1 F
        after_name = line_no_images.split(name_match.group(0), 1)[-1].strip()

        stat_match = re.match(
            r'(?P<score>[+-]?\d+|E|CUT|WD|DQ|MDF)\s*'
            r'(?P<today>[+-]?\d+|E|-)\s+'
            r'(?P<thru>F|\d+\*?)\b',
            after_name,
            re.IGNORECASE
        )
        if not stat_match:
            continue

        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        players.append({
            "pos": pos,
            "name": name,
            "score": normalize_score(stat_match.group("score")),
            "thru": normalize_thru(stat_match.group("thru")),
        })

    return players


def fetch_page(url):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def build_output(players, source_name, source_url, note):
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
        "source_name": source_name,
        "source_url": source_url,
        "note": note,
        "players": players,
    }


def main():
    existing = load_existing()

    for page in PAGES:
        try:
            html = fetch_page(page["url"])
            players = parse_espn(html)

            if players:
                output = build_output(
                    players=players,
                    source_name=page["name"],
                    source_url=page["url"],
                    note=f"Parsed {len(players)} players successfully.",
                )
                DATA_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
                print(f"Updated data.json from {page['name']} with {len(players)} players")
                return

        except Exception as e:
            print(f"Failed: {page['name']} -> {e}")

    if existing:
        existing["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        existing["note"] = "Refresh failed; kept last good data."
        DATA_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        print("Kept existing data.json because refresh failed")
    else:
        fallback = build_output(
            players=[],
            source_name="None",
            source_url="",
            note="Refresh failed and there was no previous data.",
        )
        DATA_PATH.write_text(json.dumps(fallback, indent=2), encoding="utf-8")
        print("Wrote empty fallback data.json")


if __name__ == "__main__":
    main()
