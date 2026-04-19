import json
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data.json"

URL = "https://site.web.api.espn.com/apis/v2/sports/golf/pga/leaderboard?event=401811942"


def build_output(players):
    return {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "source_name": "ESPN API",
        "source_url": URL,
        "note": f"Parsed {len(players)} players successfully.",
        "players": players,
    }


def main():
    resp = requests.get(URL)
    resp.raise_for_status()
    data = resp.json()

    players = []

    try:
        competitors = data["events"][0]["competitions"][0]["competitors"]

        for c in competitors:
            name = c["athlete"]["displayName"]
            score = c.get("score", "")
            pos = c.get("position", {}).get("displayName", "")
            thru = c.get("status", {}).get("type", {}).get("shortDetail", "")

            players.append({
                "pos": pos,
                "name": name,
                "score": score,
                "thru": thru
            })

    except Exception as e:
        print("Failed parsing JSON:", e)

    output = build_output(players)
    DATA_PATH.write_text(json.dumps(output, indent=2))
    print(f"Updated data.json with {len(players)} players")


if __name__ == "__main__":
    main()
