"""Job category & region rules. Edit keywords here to change classification."""
import re

# Order = display order. A job can match several categories.
CATEGORIES = [
    ("HEOR / RWE", [
        r"\bheor\b", r"health econ", r"outcomes? research", r"real[- ]world",
        r"\brwe\b", r"\brwd\b", r"epidemiolog", r"pharmacoepi", r"evidence generation",
        r"value evidence", r"\bheva\b", r"evidence synthesis",
    ]),
    ("Market Access", [
        r"market access", r"(patient|value|payer|customer)\s*(&|and)?\s*access",
        r"access\s*(&|and)\s*(value|pricing|reimbursement)", r"access (strategy|lead|manager|director)",
        r"pricing", r"reimbursement", r"\bpayer", r"\bhta\b", r"health technology assessment",
    ]),
    ("Clinical Trials", [
        r"clinical (trial|operations|research|study|development|project|program)",
        r"\bcra\b", r"study (manager|lead|director|start)", r"\bctm\b",
        r"site (manager|activation|management)", r"clinical scientist", r"\btrial",
    ]),
    ("Medical Affairs", [
        r"medical affairs", r"\bmsl\b", r"medical science liaison",
        r"medical (director|advisor|adviser|manager|lead)", r"medical information",
        r"scientific communication", r"medical education",
    ]),
    ("Biostat / Data Science", [
        r"biostat", r"statistic", r"\bsas\b", r"data scien", r"machine learning",
    ]),
    ("Regulatory / Safety", [
        r"regulatory", r"pharmacovigilance", r"drug safety", r"patient safety",
    ]),
    ("Commercial", [
        r"marketing", r"\bbrand\b", r"\bsales\b", r"account (manager|executive|director|specialist)",
        r"commercial", r"territory",
    ]),
]
_CAT_RE = [(name, re.compile("|".join(p), re.I)) for name, p in CATEGORIES]


def classify_category(title: str) -> list[str]:
    hits = [name for name, rx in _CAT_RE if rx.search(title or "")]
    return hits or ["Other"]


# ---------- Regions ----------
_US_STATES = ("alabama alaska arizona arkansas california colorado connecticut delaware florida georgia "
              "hawaii idaho illinois indiana iowa kansas kentucky louisiana maine maryland massachusetts "
              "michigan minnesota mississippi missouri montana nebraska nevada ohio oklahoma oregon "
              "pennsylvania tennessee texas utah vermont virginia washington wisconsin wyoming").split()
_US_STATES += ["new hampshire", "new jersey", "new mexico", "new york", "north carolina", "north dakota",
               "rhode island", "south carolina", "south dakota", "west virginia", "district of columbia"]
_US_ABBR = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
            "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC PR").split()

# Tier 1: country-level signals (most reliable)
COUNTRY = {
    "USA": r"united states|\busa?\b|u\.s\.|" + "|".join(rf"\b{s}\b" for s in _US_STATES),
    "China": r"\bchina\b|\bchn\b|\bprc\b|mainland|hong kong|\bhkg\b",
    "Europe": (r"united kingdom|\buk\b|\bgbr\b|england|scotland|wales|ireland|\birl\b|germany|\bdeu\b|"
               r"france|\bfra\b|switzerland|\bche\b|belgium|\bbel\b|netherlands|\bnld\b|spain|\besp\b|"
               r"italy|\bita\b|sweden|\bswe\b|denmark|\bdnk\b|norway|finland|austria|\baut\b|poland|"
               r"\bpol\b|portugal|czech|hungary|greece|romania|slovakia|croatia|bulgaria|serbia|"
               r"lithuania|latvia|estonia|slovenia|luxembourg|europe"),
}
# Tier 2: city names (used only when no country signal is found)
CITY = {
    "USA": (r"boston|cambridge,?\s*ma\b|new york|princeton|lawrenceville|rahway|summit|"
            r"south san francisco|indianapolis|chicago|san diego|philadelphia|thousand oaks|"
            r"foster city|tarrytown|lexington|raleigh|durham"),
    "China": (r"shanghai|beijing|suzhou|guangzhou|shenzhen|chengdu|hangzhou|wuxi|nanjing|"
              r"tianjin|wuhan|xi'?an|changsha|shenyang|dalian|qingdao"),
    "Europe": (r"london|basel|zug|zurich|geneva|munich|frankfurt|berlin|paris|lyon|dublin|cork|"
               r"madrid|barcelona|milan|rome|amsterdam|leiden|brussels|copenhagen|stockholm|"
               r"macclesfield|stevenage|uxbridge|maidenhead|warsaw|vienna|lisbon|prague"),
}
_C1 = {k: re.compile(v, re.I) for k, v in COUNTRY.items()}
_C2 = {k: re.compile(v, re.I) for k, v in CITY.items()}
_ABBR = re.compile(r"(?:,|-)\s*(" + "|".join(_US_ABBR) + r")\b")  # case-sensitive to avoid false hits
_UNKNOWN = re.compile(r"^\s*\d+\s+locations?\s*$", re.I)


# ISO-2 country codes, used when a location ends in a code (e.g. "Durham, NC, US", "Bagsvaerd, Capital Region, DK", "IE")
_ISO = {"US": "USA", "PR": "USA", "CN": "China", "HK": "China"}
_ISO.update({c: "Europe" for c in (
    "GB UK IE DE FR CH BE NL LU ES PT IT AT DK SE NO FI IS PL CZ SK HU SI HR RO BG GR "
    "EE LV LT RS BA ME MK AL MT CY").split()})
_ISO2 = re.compile(r"^[A-Z]{2}$")


def _one_region(loc: str) -> list[str]:
    loc = loc.strip()
    if not loc or _UNKNOWN.match(loc):
        return []
    parts = [p.strip() for p in loc.split(",")]
    if (len(parts) >= 3 or len(parts) == 1) and _ISO2.match(parts[-1]):
        return [_ISO.get(parts[-1], "Other")]
    hits = [r for r, rx in _C1.items() if rx.search(loc)]
    if hits:
        return hits
    # "Munich, DE" vs "Wilmington, DE": a known European/Chinese city wins over a US state code
    hits = [r for r in ("China", "Europe") if _C2[r].search(loc)]
    if hits:
        return hits
    last = parts[-1]
    if _ISO2.match(last) and last in _ISO and last not in _US_ABBR:
        return [_ISO[last]]
    if _ABBR.search(loc) or _C2["USA"].search(loc):
        return ["USA"]
    return ["Other"]


def classify_region(location: str) -> list[str]:
    """Returns e.g. ['USA'] or ['China', 'Europe'] or ['Other']; [] means unknown (e.g. '3 Locations').
    Multiple locations can be separated by ' | ' or ';'."""
    out = []
    for part in re.split(r"\s*\|\s*|\s*;\s*", location or ""):
        for r in _one_region(part):
            if r not in out:
                out.append(r)
    if len(out) > 1 and "Other" in out:
        out.remove("Other")
    return out
