# Summit-University Neighborhood Monitor

A daily-updated public dashboard for the **Summit University Planning Council (SUPC)** that monitors city, county, and state government sources for permit applications, public hearings, road projects, and funding decisions affecting Summit-University and adjacent Saint Paul neighborhoods.

**Live dashboard:** https://summituniversityplanningcouncil.github.io/neighborhood-monitor

---

## What it monitors

| Source | What |
|---|---|
| City of Saint Paul — DSI | Building permits, demolition permits, variances |
| Saint Paul Planning Commission | Meeting agendas, hearing notices, zoning cases |
| Ramsey County | Board agendas, road/infrastructure projects |
| MnDOT / Metro Transit | Highway projects, transit corridor updates |

**Neighborhoods covered:** Summit-University, Frogtown/Thomas-Dale, Hamline-Midway, Macalester-Groveland, Cathedral Hill, Summit Hill

---

## Setup

### 1. Fork or clone this repository

```bash
git clone https://github.com/summituniversityplanningcouncil/neighborhood-monitor.git
cd neighborhood-monitor
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Verify the Saint Paul permit dataset ID

The Saint Paul DSI permit scraper uses the Socrata open data API at [data.stpaul.gov](https://data.stpaul.gov).

1. Go to [data.stpaul.gov](https://data.stpaul.gov) and search for **"building permits"**
2. Open the dataset, click **API** in the top right
3. Copy the **Dataset Identifier** (a string like `j2gg-jksy`)
4. Update `config.yml` → `sources.stpaul_permits.dataset_id`
5. Also verify that the field names (`zip_field`, `date_field`, etc.) match the dataset columns

### 4. Run the monitor locally

```bash
# Full run — fetches data and generates docs/index.html
python run.py

# Dry run — fetches and processes but doesn't write HTML
python run.py --dry-run

# Test a single scraper
python run.py --source stpaul_permits
python run.py --source stpaul_planning
python run.py --source ramsey_county
python run.py --source mndot

# Verbose output for debugging
python run.py --verbose
```

### 5. Enable GitHub Pages

1. Go to your repository's **Settings → Pages**
2. Set **Source** to `Deploy from a branch`
3. Set **Branch** to `main`, folder to `/docs`
4. Save — your dashboard will be live at `https://<your-org>.github.io/<repo-name>`

### 6. Enable the daily workflow

The GitHub Actions workflow (`.github/workflows/daily_update.yml`) runs automatically once the repository is on GitHub. It:

1. Runs all scrapers at 7 AM Central Time each day
2. Generates a new `docs/index.html`
3. Commits and pushes the updated file
4. GitHub Pages automatically publishes the update

To trigger a manual run: **Actions → Daily Neighborhood Monitor Update → Run workflow**

---

## Configuration

All settings live in `config.yml`:

| Section | Purpose |
|---|---|
| `neighborhoods` | Neighborhood names used for text-based geo filtering |
| `zip_codes` | ZIP codes used for API-based geo filtering |
| `corridors` | Street names / highway designations used for text matching |
| `flag_keywords` | Keywords that trigger the "Needs Attention" flag |
| `sources` | Enable/disable scrapers, configure URLs and dataset IDs |
| `dashboard` | Title, subtitle, council URL, max item age |

### Adding a new keyword flag

Edit `config.yml` and add a term to `flag_keywords`. No code changes needed.

### Disabling a source

Set `enabled: false` under the relevant source in `config.yml`.

---

## Project structure

```
├── config.yml                  # All configuration
├── run.py                      # Main entry point
├── requirements.txt
├── scrapers/
│   ├── stpaul_permits.py       # Saint Paul DSI (Socrata API)
│   ├── stpaul_planning.py      # Saint Paul Planning Commission (web scraper)
│   ├── ramsey_county.py        # Ramsey County board + roads (web scraper)
│   └── mndot.py                # MnDOT + Metro Transit (web scraper)
├── pipeline/
│   ├── filter.py               # Geographic filtering
│   ├── flag.py                 # Keyword auto-flagging
│   └── generate.py             # Static HTML generation
├── templates/
│   └── dashboard.html          # Jinja2 dashboard template
├── docs/
│   └── index.html              # Generated dashboard (GitHub Pages root)
└── .github/workflows/
    └── daily_update.yml        # Daily cron workflow
```

---

## Maintenance notes

- **Scrapers break when sites change their HTML.** The Socrata API scraper (`stpaul_permits.py`) is the most stable. The web scrapers for Planning, Ramsey County, and MnDOT may need occasional updates when those sites redesign. Check the GitHub Actions run logs if the dashboard stops updating.
- **To check run logs:** GitHub → Actions tab → click the most recent run
- **To add a new source:** Create a new file in `scrapers/`, add a `fetch(config)` function following the existing pattern, register it in `run.py`'s `SCRAPERS` dict, and add configuration to `config.yml`

---

## About

Built for the [Summit University Planning Council](https://www.summituniversityplanningcouncil.org), a District 8 planning council in Saint Paul, MN.
