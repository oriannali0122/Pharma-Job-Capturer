from classify import classify_category as c, classify_region as r
assert c("Director, HEOR Oncology") == ["HEOR / RWE"]
assert "Market Access" in c("Associate Director, Value & Access")
assert "HEOR / RWE" in c("Real World Evidence Scientist")
assert c("Clinical Research Associate II") == ["Clinical Trials"]
assert c("Medical Science Liaison - Retina") == ["Medical Affairs"]
assert c("Manufacturing Technician") == ["Other"]
for loc, want in [("Rahway, NJ", ["USA"]), ("USA - New Jersey - Princeton", ["USA"]),
                  ("Cambridge, Massachusetts", ["USA"]), ("Cambridge, United Kingdom", ["Europe"]),
                  ("Shanghai", ["China"]), ("CHN - Beijing", ["China"]), ("Basel", ["Europe"]),
                  ("Tokyo, Japan", ["Other"]), ("3 Locations", []), ("Remote - US", ["USA"]),
                  ("South San Francisco", ["USA"]),
                  ("Durham, NC, US", ["USA"]), ("Bangalore, Karnataka, IN", ["Other"]),
                  ("Bloomington, IN, US", ["USA"]), ("Beijing, Beijing, CN", ["China"]),
                  ("Bagsvaerd, Capital Region of Denmark, DK", ["Europe"]), ("IE", ["Europe"]),
                  ("Montreal, Quebec, CA", ["Other"]), ("Kfar Saba, Israel, IL", ["Other"]),
                  ("Tokyo, Japan | Basel, Switzerland", ["Europe"]), ("Indianapolis, IN", ["USA"]), ("Munich, DE", ["Europe"]), ("Wilmington, DE", ["USA"]), ("Paris, FR", ["Europe"]), ("Ridgefield, CT", ["USA"])]:
    assert r(loc) == want, (loc, r(loc))
print("all tests passed")
