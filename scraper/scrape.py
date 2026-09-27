"""Daily pharma job scraper -> docs/jobs.json

Usage:
  python scraper/scrape.py                 # full scrape
  python scraper/scrape.py --check         # test every company: fetch one page and show a sample job
  python scraper/scrape.py --check Bayer   # test only companies whose name contains "Bayer"
"""
import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from classify import classify_category, classify_region  # noqa: E402
from sources import FETCHERS, workday_detail  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "companies.yaml"
OUT = ROOT / "docs" / "jobs.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
SLEEP = 0.4
DETAIL_BUDGET = 600  # max "N Locations" Workday jobs to look up per run (the rest retry next run)


def parse_posted(text, today):
    t = (text or "").lower()
    if "today" in t:
        d = 0
    elif "yesterday" in t:
        d = 1
    else:
        m = re.search(r"(\d+)\+?\s*days?", t)
        if not m:
            return None
        d = int(m.group(1))
    return (today - dt.timedelta(days=d)).isoformat()


def fetch_company(s, c, max_jobs):
    """Try the main source; if it fails and a fallback is configured, try that."""
    sources_ = [c] + ([c["fallback"]] if c.get("fallback") else [])
    errors = []
    for src in sources_:
        try:
            jobs = FETCHERS[src.get("type", "workday")](s, c["name"], src["url"], max_jobs)
            if not jobs:
                raise RuntimeError("no jobs parsed")
            if src is not c:
                print(f"     note: {c['name']} main source failed ({errors[0][:80]}); used fallback {src['url']}")
            return jobs
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")
    raise RuntimeError(" | fallback: ".join(errors))


def check(cfg, s, only):
    ok = n = 0
    for c in cfg["companies"]:
        if only and only.lower() not in c["name"].lower():
            continue
        n += 1
        try:
            jobs = fetch_company(s, c, 1)
            j = jobs[0]
            print(f"  OK    {c['name']:<26} e.g. \"{j['title'][:50]}\" | {j['location'][:40]} | "
                  f"{j.get('posted') or j.get('posted_text') or 'no date'}")
            ok += 1
        except Exception as e:
            print(f"  FAIL  {c['name']:<26} {type(e).__name__}: {str(e)[:110]}")
    print(f"\n{ok}/{n} companies working")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", nargs="?", const="", default=None, metavar="NAME",
                    help="only test connectivity (optionally for one company)")
    args = ap.parse_args()

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    settings = cfg.get("settings", {})
    tz = ZoneInfo(settings.get("timezone", "America/Los_Angeles"))
    max_jobs = settings.get("max_jobs_per_company", 3000)
    include_other = settings.get("include_other_categories", False)
    allowed = set(settings.get("regions", ["USA", "China", "Europe"]))
    today = dt.datetime.now(tz).date()

    s = requests.Session()
    s.headers.update({"User-Agent": UA})

    if args.check is not None:
        return check(cfg, s, args.check)

    old, first_run = {}, True
    if OUT.exists():
        try:
            old = {j["id"]: j for j in json.loads(OUT.read_text(encoding="utf-8")).get("jobs", [])}
            first_run = not old
        except Exception:
            pass

    result, status, budget = [], [], DETAIL_BUDGET
    for c in cfg["companies"]:
        name = c["name"]
        try:
            fetched = fetch_company(s, c, c.get("max_jobs", max_jobs))
        except Exception as e:
            # On failure keep the previous jobs for this company so they don't vanish
            status.append({"company": name, "group": c.get("group", ""), "ok": False, "error": f"{type(e).__name__}: {str(e)[:700]}"})
            print(f"FAIL {name}: {e}")
            result.extend(j for j in old.values() if j["company"] == name)
            continue

        kept = 0
        # a company seen for the first time (e.g. just added) uses posting dates, so it doesn't flood "new today"
        company_first = first_run or not any(o["company"] == name for o in old.values())
        for j in fetched:
            j["categories"] = classify_category(f"{j['title']} {j.get('dept', '')}")
            if j["categories"] == ["Other"] and not include_other:
                continue
            prev = old.get(j["id"])
            if prev and prev.get("regions"):  # already known with a resolved region: reuse
                for k in ("location", "regions", "posted", "first_seen"):
                    j[k] = prev.get(k)
            else:
                j["posted"] = (prev or {}).get("posted") or j.get("posted") or parse_posted(j.get("posted_text"), today)
                regs = classify_region(j["location"])
                if not regs and "_detail" in j and budget > 0:  # Workday "3 Locations" -> look up real ones
                    budget -= 1
                    try:
                        loc, start = workday_detail(s, j)
                        j["location"] = loc or j["location"]
                        j["posted"] = start or j["posted"]
                        regs = classify_region(loc)
                        time.sleep(SLEEP)
                    except Exception:
                        pass
                if regs and not any(r in allowed for r in regs):
                    continue  # outside the configured regions
                j["regions"] = [r for r in regs if r in allowed]  # [] = unresolved: hidden, retried next run
                if prev:
                    j["first_seen"] = prev["first_seen"]
                else:  # first run: use the posting date so day one isn't "everything is new"
                    j["first_seen"] = j["posted"] if company_first and j["posted"] else today.isoformat()
            for k in ("_detail", "posted_text", "dept"):
                j.pop(k, None)
            result.append(j)
            kept += 1
        status.append({"company": name, "group": c.get("group", ""), "ok": True, "count": kept})
        print(f"OK   {name}: {len(fetched)} open, {kept} kept")

    result.sort(key=lambda j: (j["first_seen"] or "", j.get("posted") or ""), reverse=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"run_date": today.isoformat(),
                               "updated_at": dt.datetime.now(tz).isoformat(timespec="minutes"),
                               "status": status, "jobs": result},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    new = sum(1 for j in result if j["first_seen"] == today.isoformat() and j["regions"])
    print(f"\n{len(result)} jobs saved, {new} new today -> {OUT}")


if __name__ == "__main__":
    main()
