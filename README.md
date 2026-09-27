# Pharma Jobs Daily

Scrapes new job postings from major pharma and biotech careers sites every day and sorts them by
function (HEOR/RWE, Market Access, Clinical Trials, Medical Affairs, and more) and region (US, China, Europe).

Free to run: GitHub Actions scrapes on a daily schedule and GitHub Pages hosts the site.

## Deploy (about 10 minutes)

1. Create a **public** GitHub repository and upload everything in this folder, including the `.github` folder.
2. Go to **Settings → Actions → General → Workflow permissions**, choose **Read and write permissions**, and save.
3. Go to **Settings → Pages**. Set Source to **Deploy from a branch**, branch `main`, folder `/docs`, and save.
4. Open **Actions → Daily job scrape → Run workflow** to run the first scrape (about 10–20 minutes).
5. When it finishes, visit `https://<your-username>.github.io/<repo-name>/`.

After that it updates automatically every morning, Pacific time.

## Run locally

```bash
pip install -r requirements.txt
python scraper/scrape.py --check    # test every company, shows one sample job each
python scraper/scrape.py --check Bayer   # test one company
python scraper/scrape.py            # full scrape, writes docs/jobs.json
cd docs && python -m http.server     # preview at http://localhost:8000
```

## Customizing

- **Add or fix companies:** edit `config/companies.yaml`. Instructions are at the top of the file.
- **Change category rules:** edit the keywords in `scraper/classify.py`, then run `cd scraper && python test_classify.py`.
- **Change regions:** edit `regions` in `config/companies.yaml`. Jobs outside those regions are dropped.

## How it works

- Each company's own careers site is read directly (no LinkedIn or job boards). Supported platforms:
  Workday (most big pharma), SAP SuccessFactors (Novo Nordisk, Boehringer Ingelheim, Astellas,
  Daiichi Sankyo), Phenom (Merck KGaA), Eightfold (Bayer), plus Greenhouse, Lever and SmartRecruiters
  (common at biotechs). Adding a company on any of these is one line in `config/companies.yaml`.
- **"New" means the first day this tool saw the job** (`first_seen`), which is more reliable than the
  site's posting date because some roles get reposted. On the very first run the posting date is used
  instead, so day one isn't "everything is new."
- Categories come from keywords in the job title; a job can have several. Regions come from the location
  text. For postings that only say "3 Locations", the scraper opens the job's detail page to get the real
  locations.
- If a company fails, its previous day's jobs are kept and the failure is shown under "Scrape status" at
  the bottom of the page.

## Notes

- Requests are spaced 0.4 s apart. This is meant for personal job hunting, so please don't speed it up much.
- Workday occasionally blocks GitHub's servers. If a company keeps failing only on GitHub, run the scraper
  on your own computer with cron and `git push` the result.
