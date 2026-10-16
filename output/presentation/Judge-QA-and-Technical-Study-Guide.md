# Pittsburgh IQ: judge Q&A and technical study guide

Prepared from the current repository on October 16, 2026. Answers distinguish working code, synthetic evaluation, and proposed validation. Suggested answers are speaking prompts, not claims that a client has adopted the product.

## The explanation everyone should know

Pittsburgh IQ is a browser-based workspace for researching local businesses. It collects public listings, retains dated evidence, and helps users find providers, prospects, and potential partners. Users can investigate websites, review contacts, save notes, and export findings. Optional AI interprets a selected set of saved evidence. The research workflow remains usable without a model.

The application has two different kinds of search: directory filters and evidence research. Its core matching is deterministic, meaning the same records and settings produce the same ranking. Generative AI is a separate, optional step.

## Business and product questions

### 1. What problem are you solving?

**Say:** Public business information is scattered. Finding a name is only the beginning: someone still needs to inspect its website, find a contact, establish where the information came from, and preserve that research. We bring those steps into one workspace.

**Example:** An agency can return to a business profile and see a previous website observation, its date, its source, and the research notes instead of starting over.

### 2. Who is the intended user?

**Say:** Vicall is the initial use case, with professional offices and school districts as research segments. The same workspace also supports someone looking for a local supplier or potential partner.

School locations and district organizations are separate types. A school does not automatically count as a district or a purchasing decision maker.

### 3. Why not use Google Maps or a spreadsheet?

**Say:** Those tools can help find and organize businesses. Our contribution is the connected research workflow: dated evidence, website findings, reviewed roles, explicit unknowns, reusable searches, and optional AI interpretation in the same place.

We have not run a comparative usability study. Describe the workflow difference, not an unmeasured superiority claim.

### 4. What makes this more than an AI wrapper?

**Say:** The application collects and structures records, retains evidence, applies explicit matching criteria, manages research history, and exposes an API. Those capabilities work independently of the model. AI interprets a bounded selection of evidence from that system.

The distinct contribution is the assembled research system. We did not train a new foundation model.

### 5. What value have you proven for the client?

**Say:** We have demonstrated the workflow and tested retrieval on controlled examples. The intended value is less repeated research and better prepared business conversations. We still need a client-reviewed pilot to measure actual time savings and relevance.

Do not claim increased sales, revenue, conversion, or adoption.

### 6. How would you measure success next?

**Say:** Review a sample of twenty offices and school districts. Label relevant organizations, verify important contacts and website findings, and compare research time with the existing workflow. Record unsupported claims, repeated fetches, and actual model usage as well.

This is a proposed evaluation, not an existing client commitment. Include organizations with missing data and no relevant match.

### 7. Could this become a business?

**Say:** A paid shared research workspace is one possible direction. Before choosing pricing, we would validate repeated use, research quality, and willingness to pay with a focused customer group.

Pricing and market demand have not been tested. Do not invent a subscription price or market-size estimate.

### 8. What are the biggest limitations?

**Say:** Source coverage and accuracy are incomplete, decision-maker authority requires human review, and the local model is experimental. Our evaluation is small and synthetic. We have not deployed a production service or demonstrated large-scale performance.

Explain the next test for each important limitation rather than claiming the system is finished.

## How the application is built

### 9. What is the technology stack?

**Say:** The browser interface uses HTML, CSS, and JavaScript. A Python backend handles collection, research, audits, and HTTP endpoints. SQLite stores workspace state. The core app uses the Python standard library; browser rendering, team serving, and local AI have optional dependencies or runtimes.

`app.py` is the local entry point. `ui/` contains the interface. `storage.py` handles SQLite persistence. `serve.py` provides the authenticated team adapter. MongoDB is not the current authoritative workspace store, even though a legacy import utility remains in the repository.

### 10. What happens when a user searches?

1. The browser sends the question and explicit criteria to the backend.
2. The backend validates the request and reads retained organization and evidence records.
3. It applies requirements such as sector, public contact, reviewed role, or observed website issue.
4. It computes a heuristic ranking and returns reasons, evidence, and unknowns.
5. If explicitly enabled and available, AI interprets selected evidence.
6. The server validates the returned references before showing the interpretation.

The evidence-search step does not need to fetch websites or call a model. Optional AI query planning is an additional model step and can increase calls.

### 11. Where does the data come from?

**Say:** The main mapped dataset comes from OpenStreetMap through Overpass. The app also supports public-directory discovery, CSV imports, and bounded website research. Additional discoveries go through a review and promotion workflow.

The presentation's 2,603 candidates, 1,059 listed websites, and 146 email contacts describe a saved snapshot, not complete or independently verified citywide coverage. Retain OpenStreetMap attribution and source provenance.

### 12. How do you prevent duplicates and misleading records?

**Say:** We normalize records and flag possible duplicates, but do not automatically merge every similar business or branch. Human review helps establish organization identity. We keep missing data and uncertain operating status explicit.

A missing website field does not establish that no website exists. An unreachable URL does not establish business closure.

### 13. How does matching work?

**Say:** Matching uses explicit filters, category and text signals, and weighted evidence factors. Users can inspect and adjust the weights. The result is a prioritization score, not a probability that a business will buy.

Default weights in `matching.py`:

| Factor | Weight |
|---|---:|
| Relevance | 35 |
| Observed need | 20 |
| Public contact | 10 |
| Reviewed role | 10 |
| Recent evidence | 10 |
| Reviewed identity | 5 |
| Partner fit | 10 |

Only applicable factors enter the denominator. Observed need applies to prospect searches; partner fit applies to partner searches. Signals are bounded between zero and one, weighted, summed, and normalized to a score out of 100.

Service matching tokenizes requested and supplied text, removes common words, and measures overlap. It does not currently use embeddings or a trained ranking model.

### 14. Is this RAG? Is there a vector database?

**Say:** It uses a retrieval-augmented generation pattern: retrieve relevant evidence, then optionally generate an interpretation using that evidence. Our retrieval uses structured filters and lexical matching. We do not currently use a vector database or embeddings.

RAG describes the combination of retrieval and generation. Do not call the present implementation embedding-based semantic search. Adding embeddings later would require evaluation against the existing baseline.

### 15. What exactly does the model receive?

**Say:** The cloud answer step receives the question and selected business evidence, including unknowns. Private research notes are excluded from that model context. API credentials stay on the server.

Current answer-context limits in `intelligence.py` are up to ten results, eight evidence items per result, 1,600 characters per evidence text, and a 60,000-character serialized-context cap. These are character limits, not token counts. Optional query planning separately receives the question and supported choices.

### 16. How do you stop hallucinations?

**Say:** We reduce risk by limiting context, requiring structured responses, and validating cited business and evidence IDs. Invalid answers do not replace the evidence results. However, a model can cite a real source and still misinterpret it, so reference validation does not establish truth.

The validator checks that a referenced business belongs to the selected context and that each cited evidence ID belongs to that business. It does not automatically prove that the source supports every sentence.

### 17. What is the local AI experiment?

**Say:** It runs Qwen2.5 0.5B Instruct in a quantized GGUF format through llama.cpp on the laptop CPU. It is a deliberately narrow test for weak hardware, separate from the normal team deployment.

Current configuration uses two CPU threads, a 2,048-token context setting, and no GPU offload. It interprets only the first sourced candidate using up to two short evidence excerpts. It starts a loopback-only process for the request and shuts it down afterward. Only one local test runs at a time.

Quantization stores model weights at lower precision to reduce memory needs, with possible quality loss. The roughly twelve-second result was one fictional-evidence smoke test, including model load. That test also misinterpreted evidence. It is not a representative performance benchmark.

### 18. What happens when AI is unavailable?

**Say:** Directory search, evidence retrieval, notes, shortlists, and exports remain available. The app reports the AI issue and keeps the retrieved evidence. It does not require a paid model call for ordinary research.

Fresh collection still requires network access. Local model inference uses a local HTTP interface, so say “no external AI service required for the local experiment,” rather than literally “no API anywhere.”

### 19. What does the website score mean?

**Say:** The static score summarizes supported technical HTML checks at a sampled URL. It is a checklist to guide investigation, not a Google ranking, comprehensive SEO verdict, or proof that the business needs to purchase services.

The current repository also has optional browser-rendered checks, sampled internal-link checks, Google Lighthouse lab-report integration, and separate CrUX field-report integration. These are distinct reports. Live Google calls still require validation with configured credentials and quota. Lab measurements and real-user field data must not be conflated.

### 20. How do you identify decision makers?

**Say:** We support sourced public person-and-role records and unreviewed suggestions from structured data or staff pages. A researcher reviews the evidence. We do not infer purchasing authority just because someone has a job title.

This distinction is especially important for schools, where a school contact may not have district purchasing authority.

### 21. What does “memory” mean here?

**Say:** Memory means persistent application records: sourced observations, reviews, notes, saved searches, and answer history. Later research can reuse those records. It is not model training or an unlimited memory system shared automatically across every agent.

SQLite is authoritative after migration. Several record bodies are stored as JSON inside SQLite tables. Raw collection files and versioned dataset exports remain on disk. An API lets other software access the workspace; a dedicated MCP server is not included.

### 22. What happens if collection or the app crashes?

**Say:** Collection publishes a completed dataset through a version pointer, preserving the previous dataset when a refresh fails. Research and audit queues can persist and be explicitly resumed. SQLite backups protect the database, and archiving the data folder also preserves raw files and screenshots.

Jobs do not silently resume merely because Python restarts. Deployment recovery exercises on representative workloads remain future validation.

### 23. Can multiple people use it?

**Say:** There is an authenticated team adapter with viewer, researcher, and administrator roles for one shared workspace. Stale-write checks reject outdated edits in supported workflows. This is not a production multitenant platform.

Remote deployment still requires TLS, protected configuration, operational monitoring, and further testing. Use one application process per data directory as documented.

### 24. What security protections exist?

**Say:** Credentials stay server-side. Team access uses roles, salted password hashes, and browser-write token checks. Website research uses bounded fetching and private-network restrictions. Model prompts treat source text as data, and models do not receive arbitrary tool-execution authority in this answer workflow.

Password hashing uses PBKDF2-HMAC-SHA256 with 600,000 iterations. CSRF protection checks a token on browser writes. SSRF protections aim to prevent a supplied URL from making the server fetch internal resources. These controls do not establish immunity to every attack; production security review remains necessary.

### 25. How would you scale it?

**Say:** First measure bottlenecks with larger datasets and concurrent users. Likely next steps include indexed retrieval, a separate job worker, a server database where needed, and production monitoring. Tenant isolation would require deliberate design.

The current Python search builds and scans records in application code. Do not claim sublinear indexed search, distributed processing, or demonstrated million-record scale. SQLite is a reasonable local prototype choice, not proof of unlimited concurrency.

## Evaluation and difficult questions

### 26. What does the 83% result actually mean?

**Say:** In one synthetic office-prospect scenario, retrieved context contained 2,549 characters compared with 14,897 characters for the full fixture context. That is about 83% fewer characters. We have not measured an equivalent token, cost, or latency reduction in a live model comparison.

Calculation: `(1 - 2549 / 14897) × 100 = 82.889%`.

### 27. What does four out of four prove?

**Say:** Retrieval returned the exact expected result sets for four controlled synthetic cases, including one case where no result was expected. That checks the intended behavior on those fixtures. It does not establish general accuracy on Pittsburgh businesses.

Precision asks what fraction of returned results were relevant. Recall asks what fraction of relevant results were returned. The three nonempty cases recorded 1.0 for both. The empty case leaves these metrics undefined and uses exact-set agreement instead.

The office baseline had precision of one third in this fixture. Describe that narrow comparison if asked; do not generalize it into a citywide accuracy improvement.

### 28. What testing did you do?

**Say:** The repository includes unit and integration-style tests for collection, research, validation, persistence, audits, team permissions, settings, and product controls. A separate evaluation script checks four fictional retrieval scenarios against a simpler baseline.

Some provider behaviors use mocked responses. The browser audit has a documented smoke check against example.com, which does not establish broad audit accuracy. Cloud AI and Google integrations need live-provider validation. Quote a test count only from a fresh test run.

### 29. Why is AI optional in an AI challenge?

**Say:** Reliable evidence collection and retrieval are prerequisites for a useful AI answer. We made that foundation independently usable, then integrated AI for question planning and evidence interpretation. This also lets us compare model output with the underlying evidence and isolate failures.

The strongest next evaluation is whether AI interpretation improves decisions over evidence search alone. We have not yet demonstrated that improvement on a real client benchmark.

### 30. How much does it cost to run?

**Say:** Local evidence search does not require paid AI calls. Cloud usage depends on the selected model and request volume. The app records reported token usage. Hosting, ongoing collection, browser checks, and maintenance also affect operating cost.

We have not established a per-customer cost model. Avoid quoting pricing or claiming that smaller character context guarantees a specific cost saving.

### 31. Did AI help you build the app?

**Suggested truthful framing:** We used AI-assisted development. We should be precise about which implementation, testing, and design work each teammate personally performed and reviewed. We can explain the architecture and demonstrate the behaviors rather than claiming that every line was manually written.

Fill in individual contributions yourselves. Repository inspection alone cannot establish who understood or authored each part.

## File map for learning the system

| File | Responsibility |
|---|---|
| `app.py` | Local launcher, HTTP application and workspace orchestration |
| `ui/` | HTML, CSS and browser JavaScript |
| `collect_osm.py` | OpenStreetMap collection and processing |
| `neighborhoods.py` | Neighborhood matching |
| `business_research.py`, `research_workspace.py` | Public-source research and retained research workflows |
| `staff_research.py` | Public staff-role suggestions |
| `intelligence.py` | Evidence assembly, search, optional AI and answer validation |
| `matching.py` | Term overlap and weighted ranking |
| `storage.py` | SQLite persistence and database backup |
| `website_audit.py` | Bounded fetcher and static website checks |
| `rendered_audit.py`, `extended_audits.py` | Browser rendering and additional audit integrations |
| `local_ai.py`, `app_settings.py` | Experimental local inference and settings |
| `serve.py`, `manage_users.py` | Authenticated team adapter and user management |
| `docs/openapi.json` | API contract for integrations |
| `evaluate.py`, `docs/evaluation.json` | Reproducible synthetic retrieval evaluation |

## Ten-minute team rehearsal

1. Everyone explains the product in thirty seconds without saying “AI does everything.”
2. One person walks through a request from browser to Python, retrieval, optional model, validation, and display.
3. One person explains a real profile's source date, unknowns, and contact evidence.
4. One person explains the 83% calculation and why it is not a token-saving claim.
5. Practice the hardest question: “What have you proven for an actual customer?” Answer directly, then describe the proposed pilot.

If you do not know an implementation detail, say: “We have not validated that yet. Here is how we would test it.” Do not substitute a plausible technical claim for an observed behavior.
