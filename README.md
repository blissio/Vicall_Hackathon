# Vicall: Pittsburgh business research assistant

## Graphical application

**Double-click `Launch Vicall.cmd`** in this folder. It finds the working Python runtime and opens the application in your browser. No packages need to be installed. Keep the launcher running while using the app; press Ctrl+C in its window to stop it.

The master entry point is `app.py`:

```powershell
python app.py
```

On this computer, you can also run `./launch.ps1`. The application normally opens at `http://127.0.0.1:8765`. If the workspace is already running, the launcher reopens that instance. The app listens only on this computer. It is a local research tool; deploying a shared/public service would require a production server and authentication.

Features:

- Minimalist directory with snapshot statistics, category filters, contact/website filters, full-text search, sorting, and pagination.
- Business profiles with public contacts, opening hours, source dates, website links, and an OpenStreetMap map link.
- Persistent shortlists, four research stages, and notes/evidence for each business.
- Research pipeline and data-quality dashboard.
- Duplicate and incomplete-address review filters; bulk shortlist saving and selection.
- CSV export of filtered results or selected businesses, including research notes and attribution.
- Background fresh/cached collection and rebuilding from saved raw data; status/error logs; dated backups before publishing completed collection jobs.
- Responsive layouts, keyboard navigation, `/` to search, Escape to close a profile, and Ctrl+S to save research.
- Website lab: reachability and technical SEO checks, per-business evidence/fixes, audit history, batch analysis, progress/cancellation, audit filters, and CSV/JSON evidence exports.
- Neighborhood dropdown with business counts, neighborhood search, and an A–Z / Z–A sortable directory column; neighborhood fields in CSV exports.

Notes are explicitly saved with **Save research**. Leaving a profile with unsaved changes asks whether to discard them; cancel to return and save. `data/workspace.json` stores notes/stages/shortlists separately from OSM data, so collection updates preserve research. Completed jobs and prior snapshots are kept in `data/jobs/` and `data/snapshots/`; these folders can grow with repeated collection. Back up the `data` folder to preserve your workspace. Run one application instance per data folder; the launcher enforces this.

The UI lives in `ui/`, and `app.py` uses `collect_osm.py` for collection and `website_audit.py` for analysis. Keep these files, `neighborhoods.py`, and `assets/` together when moving the application. Browsing, research notes and saved audits work offline; collection, fresh website checks and external links need internet access. MongoDB is optional and is not required by the graphical app. AI-generated recommendations remain a future project stage.

### Browse by neighborhood

Choose **Neighborhood** beside the category filter, or click the **Neighborhood** column heading to sort A–Z; click again for Z–A. Businesses within each neighborhood sort by name. Unknown neighborhoods stay last in both directions. Neighborhood filtering also scopes Website lab batches and exports, and combines with category, website, contact and research filters.

The app matches OSM coordinates locally against the [City of Pittsburgh neighborhood boundaries](https://pghbridgis.pittsburghpa.gov/federated/rest/services/Neighborhoods/FeatureServer/0), bundled October 6, 2026. The current saved directory is enriched when loaded; future collection exports include the same fields. ZIP codes are not used as neighborhood substitutes. Profiles show the matching method: mapped point or approximate area center. Missing/unmatched coordinates and shared-boundary matches remain **Unknown**. See [assets/README.md](assets/README.md) for boundary provenance and update details.

### Analyze a website

Open a business profile, review or enter its website URL, then choose **Analyze**. The URL does not need to be present in OSM. Findings are saved with their URL and date; business/website identity remains unverified. The Website lab shows saved findings and can analyze up to 25 matching or shortlisted websites. You can also select up to 25 directory records and choose **Analyze selected websites**.

Results under 24 hours old are reused by batches unless **Recheck recent results** is checked. The profile's Analyze button always requests a fresh check. **Stop after current website** preserves completed results; the current check may take up to about 45 seconds. Closing Python stops pending work; completed findings persist in `data/website_audits.json`. Up to four previous audits are kept per business.

The technical SEO score is a documented static-page heuristic, not a Google ranking score. Blocked/inconclusive checks are kept distinct from low scores. See [IMPROVEMENTS.md](IMPROVEMENTS.md) for the scoring rubric, limits, and prioritized product improvements.

To use a different port or dataset:

```powershell
python app.py --port 8766
python app.py --data-dir C:\path\to\another\dataset
```

## What we are building

An assistant that helps Vicall find businesses that could benefit from SEO or website services. Given a question such as **“Which Pittsburgh cafes have verified website issues?”**, it should return a shortlist with evidence, dates, source links, and explicit unknowns.

The useful differentiator is a reusable, evidence-backed business research memory: collect information once, retain it, and reuse it across questions. Measure whether this improves recommendation quality and reduces repeated research. Model training or quantization is a separate project and is not necessary for this workflow.

## Project plan

| Stage | Work | Completion target |
| --- | --- | --- |
| 1. Collect | Query OpenStreetMap through Overpass for businesses inside Pittsburgh city limits; save original responses. | Real records, reproducible query, source timestamps. |
| 2. Clean and review | Normalize names, categories, contact fields and addresses; deduplicate OSM IDs; review possible duplicate locations. | JSONL, CSV, quality report, a manual review of 30–50 records. |
| 3. Store | Load candidates into MongoDB. Keep website findings, contacts, and AI research separate and linked by business ID. | Repeatable imports, indexed filters, documented schema. |
| 4. Enrich | Check listed websites; discover missing URLs using additional permitted sources and verify business identity. | Evidence about website status, contact channels, and potential issues for an initial 50 businesses. |
| 5. Assess | Define an opportunity rubric with the client; score verified observations and keep unknowns separate. | Ranked prospects with clear reasons and evidence. |
| 6. Add AI/API | Retrieve business records and findings, then generate grounded answers. Use exact database filters for categories/location/contact fields. | Natural-language search, business detail endpoint, CSV export. |
| 7. Evaluate and demonstrate | Compare a baseline against retrieval with stored evidence on the same questions/businesses. | Measured results and a focused five-minute presentation. |

### Scope for the first version

- Pittsburgh **city**, not all of Allegheny County or the metro area.
- Collect broadly; narrow to 1–2 categories after the client identifies good prospects.
- Included tags: `shop`, commercial `office` candidates, `craft`, selected food/health/banking/automotive amenities, and lodging.
- This is a candidate list: OSM does not establish whether a business is small, independently owned, active today, or a good customer.
- Unnamed and explicitly inactive candidates are excluded from the cleaned list but retained in raw data. Obvious noncommercial offices are excluded; other false positives can remain.
- OSM is not a complete business census. Missing website, phone, email, or address fields mean **unknown**. They do not prove that a business lacks those things.
- A source's last OSM edit date is not the date its business details were independently verified.

## Data collection: implemented

`collect_osm.py` uses Python's standard library, with no API key or third-party package required.

The first live collection on **October 6, 2026** returned 2,530 OSM elements. Cleaning produced **2,410 named business candidates**, excluded 75 unnamed elements and 45 inactive/nonbusiness candidates, and flagged 31 records for possible duplicate review.

| Field available | Candidate records |
| --- | ---: |
| Usable listed website (not yet independently verified) | 1,035 |
| Normalized phone | 1,044 |
| Email passing basic syntax checks | 145 |
| House number and street | 1,496 |

All seven cleaning tests passed, and exported counts, unique source IDs, provenance fields, and duplicate references were checked. Websites, business activity, and decision-makers have not been independently verified. The optional MongoDB loader has not been run against a database.

1. Locate the Pittsburgh administrative boundary within Pennsylvania; stop unless exactly one relation matches.
2. Query nodes, ways, and relations inside its Overpass area. Ways/relations use a bounding-box center as their approximate coordinate.
3. Cache complete responses, preserve query and retrieval time, reject partial/error responses, and retry temporary failures conservatively.
4. Clean names and contacts; retain original tag values for audit and reprocessing.
5. Use `osm:<type>:<id>` as the stable source-record ID. Matching names within 40 meters are flagged as possible duplicates, not automatically merged. This is a review heuristic and can miss duplicates.
6. Export a CSV, JSONL, and quality report. CSV cells are protected against formula interpretation from free-text source values.

### Run

With a normal Python 3.10+ installation:

```powershell
python collect_osm.py
python -m unittest -v
```

On this computer the `python`/`py` Windows aliases do not currently launch. The working bundled runtime is:

```powershell
$pythonExe = 'C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $pythonExe collect_osm.py
& $pythonExe -m unittest -v
```

Commands should run from `C:\Users\DELL\Desktop\Hackathon`.

```powershell
# Fresh snapshot; otherwise a repeated run reuses the cache.
& $pythonExe collect_osm.py --refresh

# Re-clean saved data without contacting OSM.
& $pythonExe collect_osm.py --input data/raw/businesses.json
```

Outputs:

| Path | Purpose |
| --- | --- |
| `data/raw/boundary.json` | Boundary query response and metadata |
| `data/raw/businesses.json` | Original business response and collection metadata |
| `data/collection_query.overpassql` | Exact business query |
| `data/cache/` | Saved responses keyed by endpoint and query |
| `data/processed/businesses.jsonl` | One cleaned business candidate per line |
| `data/processed/businesses.csv` | Human review/export |
| `data/processed/quality_report.json` | Counts, categories, missing fields, duplicate flags |

Raw/processed files are replaced on successful runs; the cache keeps distinct queries, not a historical snapshot of every refresh. Archive dated snapshots before refreshing if history is needed. Records absent on a future run are not automatically marked closed.

## Storage choice

**MongoDB is a reasonable next step**, because each business can accumulate different website findings and research evidence. SQL would also work; there is no requirement to use NoSQL for AI. Start with JSONL, then add MongoDB once the first dataset is reviewed.

Suggested collections:

| Collection | Contents |
| --- | --- |
| `osm_businesses` | Cleaned OSM candidates and source metadata |
| `website_observations` | Business ID, URL, check time, observed issue, evidence, confidence |
| `business_contacts` | Public business contact, role if verified, source URL and verification date |
| `research_memory` | Business ID, evidence-backed summaries, evidence references, model/version, freshness |

Do not treat OSM `operator` as a decision-maker's name. Keep identity-confirmed contacts and AI inferences distinct.

An optional loader is provided in `load_mongo.py`. Once a local MongoDB server or an Atlas database is available:

```powershell
& $pythonExe -m pip install -r requirements-mongo.txt
$env:MONGODB_URI = 'mongodb://localhost:27017/'
& $pythonExe load_mongo.py
```

The loader upserts by OSM ID, creates category/status/geospatial indexes, and stores arbitrary OSM tag keys as key/value pairs. It updates only the OSM collection. MongoDB setup and a live import are not part of the completed collection step.

## Website enrichment: next

For a small initial sample, record HTTP status, redirects, page title, meta description, HTTPS, mobile viewport, and visible business contact information. Mark timeouts or bot blocks as unknown rather than a bad website. Use a browser audit when JavaScript rendering or performance matters. A missing meta description alone does not establish a serious SEO problem.

Validate that each discovered website belongs to the business by matching its name and address/contact details. A chain's central website may not identify the local decision-maker. Respect website terms, robots rules, and conservative request rates. For an eventual URL-fetching API, validate targets and redirects to prevent requests to private/local network addresses.

Every finding should retain its URL, observation time, evidence, and method. Generate website/SEO recommendations after verification; modifying client websites is a separate authorized step.

## AI and evaluation

Start with structured queries and rules. Add retrieval of website text/evidence once it exists; embeddings are useful for semantic text search, not required for category and city filters. Have the AI cite evidence and say when a claim is unknown. Treat retrieved page text as untrusted data.

Useful demo measurements:

- Collection: number of named candidates and percentage with usable website, phone, email, and full street address.
- Quality: business/category/website identity accuracy on a manually reviewed sample; duplicate rate and unresolved cases.
- Client value: precision among the top 10 prospects, reviewed against the client's rubric, compared with a simple category-only baseline.
- Research memory: input tokens, repeated page fetches, latency, and answer accuracy for the same questions with and without retained evidence.

Report measured values, sample size, and failure cases. Do not claim token savings, revenue impact, lead conversion, or citywide coverage before measuring them.

Confirm with the client: target categories, city vs. metro geography, independent businesses vs. chains, what makes a promising customer, and which fields are essential before outreach.

## Sources and attribution

- [Overpass query language](https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL)
- [Overpass public service guidance](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html): batch and cache requests; use stored data for application queries rather than querying public Overpass per user question.
- [OSM shop/contact tags](https://wiki.openstreetmap.org/wiki/Key:shop)
- [MongoDB upserts](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/update/)
- [OpenStreetMap copyright and license](https://www.openstreetmap.org/copyright)

OSM-derived data is © OpenStreetMap contributors and licensed under ODbL. Include attribution and the license link in directory/API/export displays. Published derivative databases can carry share-alike obligations; keeping sources separate helps track provenance but is not itself a license exemption.
