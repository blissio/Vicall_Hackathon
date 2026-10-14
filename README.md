# Pittsburgh IQ — local business intelligence

A browser directory and research assistant for finding Pittsburgh-area providers, prospects, and potential partners. Developed for the Vicall hackathon challenge, with professional offices and school districts as initial research segments.

The application retains sourced findings, contacts, notes, and website checks. Optional AI interprets retrieved evidence with citations. Search and research management work without a model or API key.

## Run locally

Requires Python 3.10+. The core app uses only the standard library.

```powershell
python app.py
```

On Windows, double-click **Launch Vicall.cmd** or run `./launch.ps1`. The launcher finds Python relative to your user profile. The browser opens at `http://127.0.0.1:8765`. Keep Python running while using the app.

The default workspace starts empty. Use **Data center** for OSM collection, or **Discovery & research** for public-source listings and CSV imports. New workspaces have automation disabled until configured. Existing settings are preserved.

Collection streams progress into **View collection log**. The default Overpass source falls back to the [Private.coffee public instance](https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances) after connection/gateway failures. Rate-limit responses honor their wait rather than rotating servers. Set `VICALL_OVERPASS_ENDPOINT` before launching to use an explicit endpoint. Collection has a ten-minute limit and preserves the previous snapshot on failure.

```powershell
python app.py --port 8766 --data-dir ./my_research --no-browser
```

## Offline demonstration

```powershell
python demo.py
python app.py --data-dir ./demo_data
```

The demo contains **eight fictional organizations**, fictional public-role records, and fictional website findings. It is clearly labeled and kept separate from live data. `demo.py` refuses to overwrite a nonempty folder; use another `--output` directory for a fresh demo.

Suggested demonstration:

1. In **Research assistant**, ask “Find accounting firms” and require a public contact channel and observed technical issues.
2. Inspect the dated evidence and public role; save the result and export its CSV.
3. Search for districts using the organization filter; inspect a district and its child school.
4. Switch the purpose to **Find a provider** and search for “legal advice.”
5. Repeat a search and show retrieval using retained evidence with zero external page requests.

Do not enable network automation for the fictional demo. Its `example.test` URLs are reserved for demonstrations.

## Implemented workflows

- Directory search, filters, pagination, profiles, notes, stages, and shortlists.
- OSM collection, normalization, duplicate flags, neighborhood matching, and attribution. Education amenities are included; a school location does not automatically become a district organization.
- Public-directory and CSV discovery inbox, manual promotion, service-area records, and bounded website contact research.
- Five official-source office/district starter entries. **Add office & district starter sources** places them in the inbox for review. No buying intent or website defect is asserted; suburbs have explicit service areas.
- Organization/service reviews, school/district types, parent relationships, and cycle prevention.
- Reviewed public person/role records with URLs, dates, supporting text, and optional business channels. Person JSON-LD becomes an unreviewed suggestion. Purchasing authority is not inferred.
- Provider/prospect/partner search with transparent heuristic factors and unknowns. Sector and text matching are supported; exact controls enforce contact, role, and website requirements.
- Saved searches, answer history, sourced CSV export, and JSON evidence download.
- Optional AI using bounded retrieved evidence, cited references, token usage, and fallback to evidence search.
- Static audits, sampled-page checks, repeated metadata observations, and previous contact-research snapshots.
- Optional desktop/mobile rendering, screenshots, overflow, missing alt attributes, and unlabeled controls.
- SQLite persistence, legacy import, backups, versioned dataset publication, resumable jobs, and stale workflow-write detection.
- Authenticated team-server adapter with viewer/researcher/admin roles, CSRF protection, and access logging.

## Enable AI

Configure credentials in the process environment. They are not sent to the browser or committed.

```powershell
$env:OPENAI_API_KEY = '<your API key>'
$env:VICALL_AI_MODEL = '<a Responses model available to your account that supports structured outputs>'
python app.py
```

Select **Use AI to interpret evidence**. Retrieved public evidence and the question are sent to the provider; private research notes are excluded. Model calls may incur provider charges. The checkbox explicitly enables a call.

The model's cited business/evidence IDs are validated. This checks reference integrity, **not semantic truth**; interpretations require review. Failed/invalid responses do not replace evidence results. Live-provider validation requires your credentials.

Implementation reference: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

## Browser-rendered checks

Install the optional worker into your Python environment:

```powershell
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
python app.py
```

An installed Edge browser is used on Windows if Playwright's Chromium is absent. Set `$env:VICALL_BROWSER_CHANNEL = 'msedge'` to choose it explicitly. A project-local `.browser-deps` install is also supported.

Open a profile → **Rendered website audit** → run → refresh. The bounded subprocess routes HTTP resources through the vetted, TLS-verified fetcher. Private-network targets, non-GET requests, third-party resources, service workers, and WebSockets are blocked. Robots rules and request spacing apply.

Screenshots can omit resources; inspect the blocked-resource count. These checks do **not** produce Lighthouse, Google ranking, or Core Web Vitals scores. The static score remains a heuristic.

## Persistence and backup

`data/workspace.sqlite3` stores workflow documents, reviewed contacts, organization reviews, saved searches, answers, and the loaded organization snapshot. Existing valid workspace JSON is imported on first access. JSON compatibility exports remain; after migration, SQLite is authoritative. Editing a JSON export does not update the application.

Raw OSM responses and processed exports remain files. Collection jobs are versioned in `data/jobs/`; an active-dataset pointer switches to a completed snapshot. Old-path copies are compatibility exports. Unfinished research/audit tasks survive restarts and can be resumed explicitly. Closing Python does not silently restart a queue.

**Back up research** creates a consistent SQLite backup. Also archive the data folder to retain raw files, dataset versions, and rendered artifacts. History grows over time. Run one application process per data directory.

## API and external agents

The contract is [docs/openapi.json](docs/openapi.json); regenerate it with `python build_openapi.py`.

For local external-agent access, set `VICALL_API_TOKEN` to a long random server-side credential before launching. Send `Authorization: Bearer <credential>`. Browser requests use the temporary `X-Vicall-Token`. Keep credentials out of URLs.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/search` | Search retained evidence and return explained matches |
| `POST /api/ask` | Search and optionally interpret with AI |
| `GET /api/business?id=…` | Business, public roles, and evidence |
| `POST /api/workflow` | Notes, stage, shortlist, and status reviews |
| `POST /api/organization` | Organization/services/parent review |
| `POST /api/person` | Sourced public person/role |
| `POST /api/saved-search` | Save reusable criteria |
| `POST /api/export` | CSV with contacts, findings, notes, and attribution |
| `POST /api/research-resume` | Resume unfinished research |
| `POST /api/audit-resume` | Resume unfinished static audits |

Example `/api/ask` body:

```json
{"question":"Find accounting firms","intent":"prospects","require_contact":true,"require_website_issue":true,"limit":10,"use_ai":false}
```

Workflow clients should include the last-read `expected_updated_at` (or `null` for a new workflow). Stale updates are rejected. Agent systems can call the API; a dedicated MCP server is not included.

## Shared team server

The authenticated WSGI adapter serves **one shared workspace**, not isolated tenants.

```powershell
python -m pip install -r requirements-server.txt
python manage_users.py yourname --role admin
python manage_users.py teammate --role researcher
python serve.py --data-dir ./data --users ./users.json
```

Passwords are entered interactively and stored as salted hashes. Restart after account changes. `users.json` is ignored by Git. Viewers can browse/search/export; researchers maintain research; admins manage collection, automation, starter imports, and backups. Browser writes require the CSRF token.

The server binds to loopback. Remote hosting requires a TLS reverse proxy, protected configuration, backups, and deployment-specific monitoring. No public service has been deployed. Set `VICALL_TEAM_API_TOKEN` to a random credential of at least 32 characters for team API clients; it grants researcher access.

## Validation

```powershell
python -m unittest discover -v
python evaluate.py
```

[docs/evaluation.json](docs/evaluation.json) compares evidence requirements with a sector/text-only baseline on four **synthetic** scenarios. It reports expected/result sets, precision, recall, context characters, local retrieval latency, and external page requests. Context characters are not measured model tokens.

Before claiming client value, review a real sample with Reece and measure relevance, contact/identity correctness, citation support, repeated fetches, actual tokens, and latency. Fixture evaluation establishes no revenue, conversion, citywide coverage, or real-data accuracy claim.

See [docs/implementation-status.md](docs/implementation-status.md) for remaining validation. Historical collection notes are preserved in [docs/legacy-project-notes.md](docs/legacy-project-notes.md); their counts are not asserted as this checkout's current dataset.

OSM-derived data is © OpenStreetMap contributors under [ODbL](https://www.openstreetmap.org/copyright). Other sources retain their own provenance and terms. Source dates indicate observations, not verified operation. Missing information remains unknown.

## Added research and audit controls

Directory website status now uses separate dot and text containers so labels remain readable. Profiles support editing sourced public roles with stale-save protection. Staff-page cards and name/role headings produce unreviewed suggestions; purchasing authority still requires human confirmation.

The research assistant supports desired-service and complementary-partner terms, shared ranking weights, and optional AI query planning. Service matching compares sourced text terms; it is not embedding-based semantic matching. Explicit filters override planned filters. Organization and contact API clients should send the last-read `expected_revision` (or `null` for a new record).

Collection progress survives restart. Data center controls stop collection or resume an unfinished job using available saved source responses. A stopped or failed collection preserves the published directory.

Business profiles offer bounded same-origin link checks and Google Lighthouse lab reports. Temporary failures remain inconclusive. PageSpeed can require API access/quota: set `PAGESPEED_API_KEY` in the server environment when needed. Real-user Core Web Vitals use a separate `CRUX_API_KEY` with Chrome UX Report API enabled (or the PageSpeed key if enabled for both). Google receives the chosen public website URL; research notes are not sent. Lab and real-user observations remain distinct, dated reports with history and downloadable evidence. Live Google and AI calls have not been validated without configured credentials.

New endpoints: `POST /api/matching-settings`, `POST /api/collect-cancel`, `POST /api/collect-resume`, `POST /api/link-audit`, `POST /api/performance-audit`, `POST /api/field-audit`, and corresponding saved-report GET endpoints. See the generated OpenAPI contract for request fields.
