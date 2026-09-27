"""One fetcher per careers-site platform.

Every fetcher has the signature  fetch(session, name, url, max_jobs) -> list[dict]
and returns jobs shaped like:
    {"id", "company", "title", "location", "url", "posted" (YYYY-MM-DD or None), optional "dept"}
Workday jobs may also carry "posted_text" and "_detail" (used by scrape.py).
Fetchers stop after the first page once they have max_jobs jobs, which is how --check samples them.
"""
import datetime as dt
import json
import re
import time
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

PAGE_SLEEP = 0.4
HTML = {"Accept": "text/html,application/xhtml+xml", "Content-Type": None}
JSON = {"Accept": "application/json", "Content-Type": "application/json"}


# ---------------- helpers ----------------
_MONTHS = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def to_date(v):
    """Best-effort conversion of the many date formats careers sites use -> 'YYYY-MM-DD'."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):  # epoch seconds or milliseconds
        return dt.datetime.fromtimestamp(v / 1000 if v > 1e11 else v, dt.timezone.utc).date().isoformat()
    s = str(v).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    if s.isdigit():
        return to_date(int(s))
    m = re.match(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})", s)            # 26 Sept 2026
    if m and m.group(2).lower() in _MONTHS:
        return dt.date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
    m = re.match(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", s)          # Sep 26, 2026
    if m and m.group(1).lower() in _MONTHS:
        return dt.date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
    m = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s)                       # 26/09/2026 or 09/26/2026
    if m:
        a, b, y = map(int, m.groups())
        d, mo = (a, b) if a > 12 else (b, a) if b > 12 else (a, b)
        try:
            return dt.date(y, mo, d).isoformat()
        except ValueError:
            return None
    return None


def _text(el):
    return el.get_text(" ", strip=True) if el else ""


def _strip_tags(s):
    return re.sub(r"<[^>]+>", " ", s or "").strip()


# ---------------- Workday ----------------
WD_RE = re.compile(r"https?://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)")


def _wd_parts(url):
    m = WD_RE.match(url.strip())
    if not m:
        raise ValueError(f"not a Workday careers URL (needs .../<site>): {url}")
    tenant, wd, site = m.groups()
    base = f"https://{tenant}.{wd}.myworkdayjobs.com"
    return f"{base}/wday/cxs/{tenant}/{site}", f"{base}/{site}"


WD_CAP = 2000  # Workday refuses to page past roughly the first 2,000 results of one search


def _wd_page(s, api, facets, offset):
    r = s.post(f"{api}/jobs", json={"appliedFacets": facets, "limit": 20, "offset": offset, "searchText": ""},
               headers=JSON, timeout=30)
    if r.status_code == 422 and offset > 0:
        return None  # hit the paging cap: stop this slice quietly
    r.raise_for_status()
    return r.json()


def _wd_collect(s, name, api, public, facets, max_jobs, out, seen):
    offset, total = 0, None
    while True:
        data = _wd_page(s, api, facets, offset)
        if data is None:
            break
        if total is None:
            total = data.get("total") or 0
        posts = data.get("jobPostings") or []
        if not posts:
            break
        for p in posts:
            path = p.get("externalPath")
            if path and path not in seen:
                seen.add(path)
                out.append({"id": f"{name}|{path}", "company": name, "title": (p.get("title") or "").strip(),
                            "location": p.get("locationsText") or "", "posted_text": p.get("postedOn") or "",
                            "url": public + path, "_detail": api + path})
        offset += 20
        if offset >= min(total, WD_CAP) or len(out) >= max_jobs:
            break
        time.sleep(PAGE_SLEEP)
    return total


def _wd_split_facet(facets):
    """Pick a facet (country first, then job category) whose every value is under the paging cap."""
    flat = []

    def walk(items):
        for f in items or []:
            vals = f.get("values") or []
            if vals and all("count" in v for v in vals):
                flat.append((f.get("facetParameter", ""), vals))
            for v in vals:
                if v.get("values"):
                    walk([v])
    walk(facets)
    rank = lambda p: (0 if "country" in p.lower() else 1 if "family" in p.lower() else 2)
    for param, vals in sorted(flat, key=lambda x: rank(x[0])):
        if param and max(v["count"] for v in vals) < WD_CAP:
            return param, vals
    return None


def fetch_workday(s, name, url, max_jobs):
    api, public = _wd_parts(url)
    first = _wd_page(s, api, {}, 0)
    total = first.get("total") or 0
    out, seen = [], set()
    if total < WD_CAP - 50 or max_jobs <= 20:
        _wd_collect(s, name, api, public, {}, max_jobs, out, seen)
        return out
    split = _wd_split_facet(first.get("facets"))
    if not split:  # no usable facet: take what the cap allows
        _wd_collect(s, name, api, public, {}, max_jobs, out, seen)
        return out
    param, vals = split
    for v in vals:
        _wd_collect(s, name, api, public, {param: [v["id"]]}, max_jobs, out, seen)
        if len(out) >= max_jobs:
            break
    return out


def workday_detail(s, job):
    r = s.get(job["_detail"], headers=JSON, timeout=30)
    r.raise_for_status()
    info = r.json().get("jobPostingInfo", {})
    locs = [info.get("location")] + (info.get("additionalLocations") or [])
    return " | ".join(l for l in locs if l), info.get("startDate")


# ---------------- SAP SuccessFactors career sites ----------------
# Used by Novo Nordisk, Boehringer Ingelheim, Astellas, Daiichi Sankyo.
# Classic sites render a results table at /search/; newer "Career Site Builder" sites load
# results from /services/recruiting/v1/jobs. We try the table first, then the JSON API.
def fetch_successfactors(s, name, url, max_jobs):
    base = url.rstrip("/")
    notes = []
    for step in (_sf_table, _sf_api, _sf_rss):
        try:
            jobs = step(s, name, base, max_jobs)
            if jobs:
                return jobs
            notes.append(f"{step.__name__}: 0 jobs")
        except Exception as e:
            notes.append(f"{step.__name__}: {type(e).__name__} {str(e)[:60]}")
    raise RuntimeError("SuccessFactors: " + "; ".join(notes))


def _sf_table(s, name, base, max_jobs):
    out, start, total = [], 0, None
    while len(out) < max_jobs:
        r = s.get(f"{base}/search/", params={"q": "", "sortColumn": "referencedate", "sortDirection": "desc",
                                             "startrow": start, "locale": "en_US"}, headers=HTML, timeout=30)
        if r.status_code >= 400:
            return out
        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select("tr.data-row")
        if not rows:
            break
        if total is None:
            m = re.search(r"of\s*([\d.,]+)", _text(soup.select_one(".paginationLabel")))
            total = int(re.sub(r"[.,]", "", m.group(1))) if m else None
        for tr in rows:
            a = tr.select_one("a.jobTitle-link") or tr.select_one("a[href*='/job/']")
            if not a or not a.get("href"):
                continue
            href = urljoin(base + "/", a["href"])
            jid = (re.search(r"/(\d+)(?:-[a-z]{2}_[A-Z]{2})?/?$", href) or [None, href])[1]
            out.append({"id": f"{name}|{jid}", "company": name, "title": _text(a),
                        "location": _text(tr.select_one(".jobLocation")),
                        "dept": _text(tr.select_one(".jobFacility") or tr.select_one(".jobDepartment")),
                        "posted": to_date(_text(tr.select_one(".jobDate"))), "url": href})
        start += len(rows)
        if total and start >= total:
            break
        time.sleep(PAGE_SLEEP)
    return out


def _sf_api(s, name, base, max_jobs):
    home = s.get(base + "/", params={"locale": "en_US"}, headers=HTML, timeout=30)
    m = re.search(r"CSRFToken\s*[=:]\s*['\"]([^'\"]+)", home.text) or \
        re.search(r"['\"]csrf[_-]?token['\"]\s*[:=]\s*['\"]([^'\"]+)", home.text, re.I)
    headers = dict(JSON, Origin=base, Referer=base + "/", **{"X-Requested-With": "XMLHttpRequest"})
    if m:
        headers["X-CSRF-Token"] = m.group(1)
    out, page, total = [], 0, None
    while len(out) < max_jobs:
        body = {"locale": "en_US", "pageNumber": page, "sortBy": "", "keywords": "", "location": "",
                "facetFilters": {}, "brand": "", "skills": [], "categoryId": 0, "alertId": "", "rcmCandidateId": ""}
        r = s.post(f"{base}/services/recruiting/v1/jobs", json=body, headers=headers, timeout=30)
        if r.status_code >= 400:
            if not out:
                raise RuntimeError(f"HTTP {r.status_code}")
            return out
        data = r.json()
        total = total or data.get("totalJobs")
        items = data.get("jobSearchResult") or []
        if not items:
            break
        for it in items:
            j = it.get("response", it)
            jid = j.get("id")
            title = j.get("unifiedStandardTitle") or j.get("title") or j.get("jobTitle") or ""
            locs = j.get("jobLocationShort") or j.get("jobLocation") or []
            locs = [locs] if isinstance(locs, str) else locs
            slug = j.get("urlTitle") or re.sub(r"[^\w]+", "-", title).strip("-")
            out.append({"id": f"{name}|{jid}", "company": name, "title": _strip_tags(title),
                        "location": " | ".join(_strip_tags(x) for x in locs if x),
                        "posted": to_date(j.get("unifiedStandardStart") or j.get("postingStartDate")
                                          or j.get("unifiedStandardDate")),
                        "url": f"{base}/job/{slug}/{jid}-en_US/"})
        page += 1
        if total and len(out) >= total:
            break
        time.sleep(PAGE_SLEEP)
    return out


def _sf_rss(s, name, base, max_jobs):
    """SuccessFactors job RSS feed. Item titles usually look like 'Job Title (City, ST, CC, zip)'."""
    r = s.get(f"{base}/services/rss/job/", params={"locale": "en_US", "keywords": "()"},
              headers={"Accept": "application/rss+xml,application/xml,text/xml", "Content-Type": None}, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}")
    soup = BeautifulSoup(r.content, "xml")
    out = []
    for it in soup.find_all("item")[:max_jobs]:
        raw = _text(it.find("title"))
        link = _text(it.find("link"))
        m = re.match(r"^(.*)\s+\(([^()]*)\)\s*$", raw)
        title, loc = (m.group(1), m.group(2)) if m else (raw, "")
        loc = re.sub(r",\s*\d[\w -]*$", "", loc)  # drop trailing postal code
        jid = (re.search(r"/(\d+)(?:-[a-z]{2}_[A-Z]{2})?/?$", link) or [None, link])[1]
        out.append({"id": f"{name}|{jid}", "company": name, "title": title.strip(), "location": loc.strip(),
                    "posted": to_date(_text(it.find("pubDate"))[5:16]), "url": link})
    return out


# ---------------- Phenom (Merck KGaA / EMD, also jobs.merck.com) ----------------
def _phenom_ddo(html):
    i = html.find("phApp.ddo")
    if i < 0:
        raise RuntimeError("Phenom: page has no phApp.ddo data block")
    i = html.index("{", i)
    return json.JSONDecoder().raw_decode(html, i)[0]


def fetch_phenom(s, name, url, max_jobs):
    base = url.rstrip("/")
    out, frm, total = [], 0, None
    while len(out) < max_jobs:
        r = s.get(f"{base}/search-results", params={"from": frm, "s": 1}, headers=HTML, timeout=30)
        r.raise_for_status()
        block = _phenom_ddo(r.text).get("eagerLoadRefineSearch") or {}
        data = block.get("data") or {}
        jobs = data.get("jobs") or []
        total = total or block.get("totalHits") or data.get("totalHits")
        if not jobs:
            break
        for j in jobs:
            jid = j.get("jobId") or j.get("jobSeqNo") or j.get("reqId")
            locs = j.get("multi_location") or [j.get("cityStateCountry") or j.get("location") or ""]
            out.append({"id": f"{name}|{jid}", "company": name, "title": (j.get("title") or "").strip(),
                        "location": " | ".join(l for l in locs if l),
                        "dept": j.get("category") or "",
                        "posted": to_date(j.get("postedDate") or j.get("dateCreated")),
                        "url": f"{base}/job/{jid}"})
        frm += len(jobs)
        if total and frm >= total:
            break
        time.sleep(PAGE_SLEEP)
    return out


# ---------------- Eightfold (Bayer's talent.bayer.com) ----------------
def fetch_eightfold(s, name, url, max_jobs):
    p = urlparse(url)
    host = f"{p.scheme}://{p.netloc}"
    m = re.search(r"domain=([\w.-]+)", p.query)
    domain = m.group(1) if m else re.sub(r"^(talent|careers|jobs)\.", "", p.netloc)
    out, start, total = [], 0, None
    while len(out) < max_jobs:
        r = s.get(f"{host}/api/apply/v2/jobs", params={"domain": domain, "start": start, "num": 50,
                                                       "sort_by": "timestamp"}, headers=JSON, timeout=30)
        r.raise_for_status()
        data = r.json()
        total = total or data.get("count")
        jobs = data.get("positions") or []
        if not jobs:
            break
        for j in jobs:
            locs = j.get("locations") or [j.get("location") or ""]
            out.append({"id": f"{name}|{j['id']}", "company": name, "title": (j.get("name") or "").strip(),
                        "location": " | ".join(l for l in locs if l), "dept": j.get("department") or "",
                        "posted": to_date(j.get("t_create") or j.get("t_update")),
                        "url": j.get("canonicalPositionUrl") or f"{host}/careers/job/{j['id']}"})
        start += len(jobs)
        if total and start >= total:
            break
        time.sleep(PAGE_SLEEP)
    return out


# ---------------- Greenhouse / Lever / SmartRecruiters (biotechs) ----------------
def fetch_greenhouse(s, name, token, max_jobs):
    r = s.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", headers=JSON, timeout=30)
    r.raise_for_status()
    return [{"id": f"{name}|{j['id']}", "company": name, "title": j["title"].strip(),
             "location": (j.get("location") or {}).get("name", ""),
             "posted": to_date(j.get("first_published") or j.get("updated_at")),
             "url": j["absolute_url"]} for j in r.json().get("jobs", [])[:max_jobs]]


def fetch_lever(s, name, token, max_jobs):
    r = s.get(f"https://api.lever.co/v0/postings/{token}?mode=json", headers=JSON, timeout=30)
    r.raise_for_status()
    return [{"id": f"{name}|{j['id']}", "company": name, "title": j["text"].strip(),
             "location": (j.get("categories") or {}).get("location", ""),
             "posted": to_date(j.get("createdAt")), "url": j["hostedUrl"]} for j in r.json()[:max_jobs]]


def fetch_smartrecruiters(s, name, token, max_jobs):
    out, offset = [], 0
    while len(out) < max_jobs:
        r = s.get(f"https://api.smartrecruiters.com/v1/companies/{token}/postings",
                  params={"limit": 100, "offset": offset}, headers=JSON, timeout=30)
        r.raise_for_status()
        items = r.json().get("content") or []
        for j in items:
            loc = j.get("location") or {}
            out.append({"id": f"{name}|{j['id']}", "company": name, "title": j["name"].strip(),
                        "location": ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x),
                        "posted": to_date(j.get("releasedDate")),
                        "url": f"https://jobs.smartrecruiters.com/{token}/{j['id']}"})
        if len(items) < 100:
            break
        offset += 100
        time.sleep(PAGE_SLEEP)
    return out


FETCHERS = {
    "workday": fetch_workday, "successfactors": fetch_successfactors, "phenom": fetch_phenom,
    "eightfold": fetch_eightfold, "greenhouse": fetch_greenhouse, "lever": fetch_lever,
    "smartrecruiters": fetch_smartrecruiters,
}
