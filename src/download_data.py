"""Download daily research prices for the study tickers from Yahoo Finance.

Settings (tickers, dates) are read from the "My settings" section of CLAUDE.md.

House rules this follows:
  - data/prices.parquet is reused. Only tickers it doesn't have yet (for the
    current Data dates) are downloaded; tickers already there are never touched.
  - After every download, prints rows, first date, last date and missing days per ticker.
  - Writes data/prices.sha256 so backtests can check the file hasn't changed.

Files:
  data/prices.parquet          long table: date, ticker, open, high, low, close, volume
  data/prices_meta.json        per ticker: the start/end dates it was downloaded with
  data/prices.sha256           SHA-256 fingerprint of prices.parquet
  data/download_summary.csv    one row per ticker: first/last date, rows, missing days
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "CLAUDE.md"
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
PRICES = DATA_DIR / "prices.parquet"
META = DATA_DIR / "prices_meta.json"
HASH = DATA_DIR / "prices.sha256"
COLUMNS = ["date", "ticker", "open", "high", "low", "close", "volume"]


def read_settings() -> dict:
    text = RULES.read_text(encoding="utf-8")
    data_line = re.search(r"^- Data: from (\d{4}-\d{2}-\d{2}) through (\d{4}-\d{2}-\d{2})", text, re.M)
    tickers_line = re.search(r"^- Study tickers: (.+?)\s*$", text, re.M)
    market_line = re.search(r"^- Market ticker: (\S+?)\.", text, re.M)
    if not (data_line and tickers_line and market_line):
        sys.exit("Could not read the Data / Study tickers / Market ticker lines from CLAUDE.md")
    return {
        "start": data_line.group(1),
        "last_day": data_line.group(2),
        "tickers": tickers_line.group(1).rstrip(".").split(),
        "market": market_line.group(1),
    }


def fetch(tickers: list[str], start: str, end_exclusive: str) -> pd.DataFrame:
    raw = yf.download(
        tickers, start=start, end=end_exclusive, interval="1d",
        auto_adjust=True, actions=False, group_by="ticker",
        threads=True, progress=False, multi_level_index=True,
    )
    if raw.empty:
        return pd.DataFrame(columns=COLUMNS)
    long = raw.stack(level=0, future_stack=True).reset_index()
    long.columns = [str(c).lower() for c in long.columns]
    long = long.rename(columns={"level_1": "ticker"})
    long["date"] = pd.to_datetime(long["date"]).dt.tz_localize(None).dt.normalize()
    return long.dropna(subset=["close"])[COLUMNS]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    s = read_settings()
    end_exclusive = (date.fromisoformat(s["last_day"]) + timedelta(days=1)).isoformat()
    wanted = {"start": s["start"], "end": s["last_day"]}

    prices = pd.read_parquet(PRICES) if PRICES.exists() else pd.DataFrame(columns=COLUMNS)
    meta = json.loads(META.read_text()) if META.exists() else {}

    # Keep a ticker only if it was downloaded with the same dates as the settings now say.
    keep = [t for t in s["tickers"] if meta.get(t) == wanted and t in set(prices["ticker"])]
    prices = prices[prices["ticker"].isin(keep)]
    meta = {t: meta[t] for t in keep}
    need = [t for t in s["tickers"] if t not in keep]

    if not need:
        print("Every study ticker is already in data/prices.parquet for these dates. Nothing downloaded.")
    else:
        print(f"Reusing {len(keep)} tickers. Downloading {len(need)}: {' '.join(need)}")
        print(f"Dates: {s['start']} through {s['last_day']} (end passed to yfinance: {end_exclusive})")
        new = fetch(need, s["start"], end_exclusive)
        for attempt in range(3):
            missing = [t for t in need if t not in set(new["ticker"])]
            if not missing:
                break
            print(f"Retry {attempt + 1}: {missing}")
            time.sleep(5 * (attempt + 1))
            for t in missing:
                part = fetch([t], s["start"], end_exclusive)
                if not part.empty:
                    new = pd.concat([new, part], ignore_index=True)
        for t in set(new["ticker"]):
            meta[t] = wanted
        prices = pd.concat([prices, new], ignore_index=True)

    prices = (prices.drop_duplicates(["date", "ticker"])
              .sort_values(["ticker", "date"]).reset_index(drop=True))

    # ---- report and checks ----
    problems: list[str] = []
    market_days = pd.DatetimeIndex(prices.loc[prices["ticker"] == s["market"], "date"])
    rows = []
    for t in s["tickers"]:
        p = prices[prices["ticker"] == t]
        if p.empty:
            problems.append(f"{t}: no data")
            rows.append({"ticker": t, "rows": 0})
            continue
        first, last = p["date"].min(), p["date"].max()
        expected = market_days[(market_days >= first) & (market_days <= last)]
        missing_days = len(expected.difference(pd.DatetimeIndex(p["date"])))
        bad = int((p[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
        if bad:
            problems.append(f"{t}: {bad} rows with zero or negative prices")
        if missing_days:
            problems.append(f"{t}: {missing_days} market days missing inside its range")
        if last.date().isoformat() != s["last_day"]:
            problems.append(f"{t}: last date {last.date()} is not {s['last_day']}")
        rows.append({"ticker": t, "rows": len(p), "first_date": first.date(),
                     "last_date": last.date(), "missing_days": missing_days})

    if need:
        DATA_DIR.mkdir(exist_ok=True)
        prices.to_parquet(PRICES, index=False)
        META.write_text(json.dumps(meta, indent=2, sort_keys=True))
        HASH.write_text(sha256(PRICES) + "\n")
    summary = pd.DataFrame(rows)
    summary.to_csv(DATA_DIR / "download_summary.csv", index=False)

    LOG_DIR.mkdir(exist_ok=True)
    with (LOG_DIR / "download_data.log").open("a", encoding="utf-8") as f:
        f.write(f"{pd.Timestamp.now():%Y-%m-%d %H:%M:%S} yfinance {yf.__version__} "
                f"downloaded={len(need)} reused={len(keep)} rows={len(prices)} problems={len(problems)}\n")
        for line in problems:
            f.write(f"    {line}\n")

    print(summary.to_string(index=False))
    print(f"\n{len(prices):,} rows in {PRICES}")
    print(f"SHA-256: {HASH.read_text().strip() if HASH.exists() else 'missing'}")
    if problems:
        print("\nChecks flagged:")
        for line in problems:
            print("  -", line)
    else:
        print("All checks passed.")


if __name__ == "__main__":
    main()
