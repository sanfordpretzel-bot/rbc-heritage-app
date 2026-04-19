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
        "name": "PGA TOUR RBC Heritage leaderboard",
        "url": "https://www.pgatour.com/tournaments/2026/rbc-heritage/R2026012/leaderboard",
    },
    {
        "name": "ESPN RBC Heritage leaderboard",
        "url": "https://www.espn.com/golf/leaderboard/_/tournamentId/401811942",
    },
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
    m = re.match(r"^([+-]?\d+)$", score)
    if m:
        n = int(m.group(1))
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
        return 9000 + sorted(SPECIAL_SCORES).index(s)
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


def parse_pga_tour(html):
    """
    Broad HTML parser using visible text patterns.
    This is intentionally defensive because page markup may change.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [clean_text(x) for x in text.splitlines() if clean_text(x)]

    players = []
    seen = set()

    # Looks for patterns like:
    # T1 / 1 / 2
    # Player Name
    # -12 / E / WD
    # F / 13 / 4*
    #
    # The PGA text snippets exposed by search results show Pos, Player, Tot, Thru.
    for i in range(len(lines) - 3):
      pos = lines[i].upper()
      name = lines[i + 1]
      score = lines[i + 2].upper()
      thru = lines[i + 3].upper()

      if not re.match(r"^(T?\d+)$", pos):
          continue
      if len(name.split()) < 2:
          continue
      if not re.match(r"^([+-]?\d+|E|CUT|WD|DQ|MDF)$", score):
          continue
      if not re.match(r"^(F|\d+\*?|-)$", thru):
          continue

      key = name.lower()
      if key in seen:
          continue
      seen.add(key)

      players.append({
          "pos": pos,
          "name": name,
          "score": normalize_score(score),
          "thru": normalize_thru(thru),
      })

    return players


def parse_espn(html):
    """
    ESPN page text is often easier to recover than the raw DOM structure.
    We search scripts/text for leaderboard-like rows.
    """
    soup = BeautifulSoup(html, "html.parser")

    script_text = "\n".join(s.get_text(" ", strip=True) for s in soup.find_all("script"))
    body_text = soup.get_text("\n", strip=True)
    haystack = script_text + "\n" + body_text

    players = []
    seen = set()

    # Very tolerant name pattern:
    # catches names in leaderboard-like text blocks
    pattern = re.compile(
        r'(?P<pos>T?\d+)\s+'
        r'(?P<name>[A-Z][A-Za-z.\'’\-]+(?:\s+[A-Z][A-Za-z.\'’\-]+)+)\s+'
        r'(?P<score>[+-]?\d+|E|CUT|WD|DQ|MDF)\s+'
        r'(?P<thru>F|\d+\*?)'
    )

    for m in pattern.finditer(haystack):
        name = clean_text(m.group("name"))
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        players.append({
            "pos": clean_text(m.group("pos")).upper(),
            "name": name,
            "score": normalize_score(m.group("score")),
            "thru": normalize_thru(m.group("thru")),
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

            players = []
            if "pgatour.com" in page["url"]:
                players = parse_pga_tour(html)
            elif "espn.com" in page["url"]:
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
