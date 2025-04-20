import time, csv, os
import requests
from bs4 import BeautifulSoup

MATCH_URL = "https://crex.com/scoreboard/T3V/1PD/38th-Match/F/G/csk-vs-mi-38th-match-indian-premier-league-2025/live"
CSS_SELECTOR = "body > app-root > div > app-match-details > div.live-score-header.mob-none > app-match-details-wrapper > div > div > div:nth-child(1) > div.team-content > div.team-score > div"
CSV_PATH = "live_score_clean.csv"

last_recorded_over = -1.0  # Track the last over recorded

def init_csv():
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["score", "overs"])

def fetch_score() -> str:
    r = requests.get(MATCH_URL, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    node = soup.select_one(CSS_SELECTOR)
    if not node:
        raise RuntimeError(f"Selector not found: {CSS_SELECTOR}")
    return node.get_text(strip=True)

def format_score(raw: str):
    if "-" in raw:
        parts = raw.split("-")
        if len(parts) == 2:
            runs = parts[0]
            right = parts[1]
            if "." in right:
                wickets = right[0]
                overs = right[1:]  # includes dot
                return [f"{runs}-{wickets}", overs]
    return [raw, ""]

def main():
    global last_recorded_over
    init_csv()
    while True:
        try:
            raw_score = fetch_score()
            formatted = format_score(raw_score)

            overs = formatted[1]
            if overs:
                over_float = float(overs)
                if over_float.is_integer() and over_float > last_recorded_over:
                    last_recorded_over = over_float
                    with open(CSV_PATH, "a", newline="") as f:
                        writer = csv.writer(f)
                        writer.writerow(formatted)
                    print(f"Saved: {formatted[0]}, {formatted[1]}")
                else:
                    print(f"Skipped (not full over): {formatted[0]}, {formatted[1]}")
            else:
                print("Overs data not found in score.")

        except Exception as e:
            print("Error scraping:", e)

        time.sleep(1)

if __name__ == "__main__":
    main()