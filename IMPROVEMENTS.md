# Vicall improvements and next steps

## Added in this refinement

- Credential-free discovery from Pittsburgh's public business/contractor licensing records, with an optional county business directory, a review inbox, repeat-import deduplication, and source coverage limits.
- Automated contact research across up to four website pages, with public phone/email/social/contact-page observations and field-level source URLs/dates. Original OSM contacts remain intact; differences prompt review.
- Separate operating, website reachability, website identity, contact availability, and location-type statuses; evidence-backed researcher reviews.
- Home/service-area business records without map pins or residential addresses, public-listing and CSV submissions, and preserved review state across updates.
- Persistent settings and task progress for bounded background research while Python is open; interrupted jobs are reported explicitly. Complete queue resumption remains a future improvement.

- A Website lab for live checks of listed or researcher-entered business URLs.
- HTTP reachability, status codes, safe redirect handling, TLS verification, fetch timing, robots rules, and optional sitemap probing.
- Evidence for page titles, descriptions, H1 headings, mobile viewport, indexing directives, canonical links, image alt attributes, internal links, and JSON-LD presence/syntax.
- A transparent 0–100 technical checklist: **80+ strong basics**, **50–79 needs review**, **under 50 needs work**. Observed indexing blockers cap the score at 49. These thresholds are our heuristic, not Google's ranking model.
- Separate inconclusive results for bot challenges, robots restrictions, timeouts, non-HTML responses, very sparse JavaScript pages, and truncated content. These receive no SEO grade.
- Suggested improvements, timestamped evidence, up to four previous results, downloadable JSON evidence, and audit fields in CSV exports.
- Audit filters, SEO sorting, single-business checks, selected/shortlisted/filtered batches (maximum 25), progress, and stop-after-current controls.
- Recent-result reuse (24 hours), an explicit recheck option, public-target-only requests, verified TLS, and conservative request spacing.
- A profile dialog that prevents interaction with the background while it is open, clearer website status labels, and readable directory-rendering functions.

## What to improve next, in priority order

| Priority | Improvement | Why it matters | Practical next step |
| --- | --- | --- | --- |
| 1 | Browser-rendered website audits | Static HTML can miss JavaScript content, broken visual layouts and poor mobile usability. | Add an optional browser worker with screenshots and Lighthouse; keep the lightweight basic audit available. |
| 1 | Stronger website/business identity matching | Researcher confirmation and name/contact signals now exist, but a chain or unrelated site can still provide misleading contacts. | Validate branch-level matches and conflicting evidence against a human-reviewed sample; retain explicit unknowns. |
| 1 | Client-defined prospect rubric | Technical SEO problems alone do not establish a good customer or budget. | Confirm target categories, service area, company size, independence and useful outreach fields with Vicall. |
| 1 | Validate the audit rubric | Present/absent HTML signals are useful but do not measure ranking performance or content quality. | Review 30–50 audits with a human, measure false positives and compare against rendered checks. |
| 2 | Multi-page SEO analysis | Contact research now samples up to four pages, but the technical SEO score still applies to one requested URL. | Add page-level metadata comparisons and a bounded internal-link check. |
| 2 | Verified contacts and decision-makers | Existing contacts are business listings, not verified owners or decision-makers. | Record public business contact source, role, date and confidence; keep uncertain matches explicit. |
| 2 | Find missing websites | Public-directory discovery now provides more leads and occasional website URLs; coverage is incomplete. | Add more licensed sources or an authorized search integration, then validate business identity before accepting a website match. |
| 2 | Resume queues and compare historical research | Research progress/settings now persist; interrupted jobs are marked and need a new run. Website-audit jobs still run in memory. | Persist/resume individual tasks safely and retain full contact/SEO change history. |
| 2 | Stronger data publishing | Collection currently publishes completed files individually with dated backups. | Commit one versioned dataset directory and switch an active pointer, so even disk errors cannot produce mixed snapshots. |
| 3 | Evidence-grounded AI research | The current system provides rules and manual research, without an AI assistant. | Retrieve verified records and findings, generate recommendations with citations, and evaluate top-10 prospect precision. |
| 3 | Richer search visibility data | The app does not know traffic, backlinks, keyword position, or real-user performance. | Use authorized Search Console/PageSpeed integrations for clients who grant access; show data provenance and cost. |
| 3 | Shared storage and collaboration | Local JSON is simple but not a multi-user database. | Add MongoDB or another database, authentication, user roles, conflict handling and backups before team hosting. |
| 3 | Packaging and usability | The app still uses a Python launcher and browser. | Package an installer, add keyboard help, persistent filters, saved searches, and an export-download fallback for embedded browsers. |

## Current audit limits

The audit observes one requested URL from this computer. A successful HTTP response does not prove that all pages work or that the site belongs to the business. An unsuccessful check can reflect local connectivity, server load, robot policies, or a bot challenge.

The score measures HTML signals with fixed weights: HTTPS 10, title 20, description 15, H1 15, viewport 10, indexing checks 15, canonical 5, alt attributes 5, and internal links 5. Advisory structured-data/social/sitemap findings do not alter it. Missing canonical links or sitemaps are not inherently SEO failures. Multiple H1 elements are not automatically penalized. Empty image alt attributes can be appropriate for decorative images.

JavaScript is not executed, image/link targets are not crawled, schema eligibility is not validated, and robots interpretation covers common agent/group/path/wildcard rules rather than all crawler-specific behavior. A very sparse scripted response is left unscored, but that heuristic does not detect every JavaScript-dependent website. Fetch time excludes robots preflight and request-spacing delays; it includes the sampled request(s), DNS, TLS, redirects and body download, and is not a Core Web Vitals metric.

## Reference guidance

- [Google SEO Starter Guide](https://developers.google.com/search/docs/fundamentals/seo-starter-guide)
- [Google robots.txt guidance](https://developers.google.com/search/docs/crawling-indexing/robots/intro)
- [Google robots meta/header directives](https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag)
- [Google title link guidance](https://developers.google.com/search/docs/appearance/title-link)
