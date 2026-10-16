# Pittsburgh IQ: five-minute presentation script

Ten slides. Timing target: 5:00, including pauses and slide changes. Rehearse at roughly 140 words per minute; use the timestamps as checkpoints. The same script appears in PowerPoint speaker notes.

## Slide 1: Who should Reece call next?
**0:00–0:25 (25 seconds)**

*Pause after the opening question. Let the room answer it silently.*

Imagine Reece opens his laptop tomorrow morning. Vicall helps businesses improve their websites. But before he can help anyone, he has to answer a simpler question: who should I call next? We built Pittsburgh IQ to make that decision better informed, and to make sure yesterday’s research is still useful tomorrow.

## Slide 2: Reece asked for a citywide resource
**0:25–0:50 (25 seconds)**

*Point to the client’s words, then look back at the judges.*

We started with website research for Vicall. Then Reece widened the idea. He wanted a smart Pittsburgh directory to help people buy services and build relationships to sell. He named professional offices and school districts as important customers. That feedback changed our direction: a shared research workflow around local organizations, with Vicall as the first use case.

## Slide 3: A real starting point
**0:50–1:15 (25 seconds)**

*Point to the candidate count, then the website count.*

Here is the working directory. Our saved Pittsburgh snapshot contains 2,603 business candidates, including 1,059 with listed websites. You can narrow the directory by neighborhood, category, or available contact information. These are starting points for research. A listing does not prove that an organization is operating, and a missing website field does not prove that it has no website.

## Slide 4: One question becomes a focused search
**1:15–1:45 (30 seconds)**

*Show the query and selected purpose. This is a captured product walkthrough.*

Now imagine someone needs a legal provider. We choose that purpose, select the legal sector, and ask a straightforward question. This search returned 22 candidates from retained evidence, without fetching another external page. The same interface supports prospect research and potential partners. For Vicall, the next step would be to focus on relevant offices, then investigate which ones have a website issue worth discussing. The requirements are visible and adjustable.

## Slide 5: The evidence stays beside the result
**1:45–2:20 (35 seconds)**

*Point to the source links and dates, then the unknowns.*

A useful result needs more than a company name. Here, Beroes Law Center comes with public references supporting the match. Each observation keeps its source and date. The app also says what it does not know, including decision-maker roles and confirmed services. Researchers can add a public person and role with evidence, but a job title does not prove purchasing authority. The next human review becomes specific and traceable.

## Slide 6: A concrete reason to investigate
**2:20–2:50 (30 seconds)**

*Point to the saved URL and checklist. Avoid describing the score as a search ranking.*

For Vicall, website analysis makes the research more actionable. This saved check records the exact URL, response, observation time, and technical findings. It can flag details such as a missing main heading for a person to investigate. A blocked request stays inconclusive. The score is a static checklist, not a Google ranking. That distinction matters: the goal is a better informed conversation with a business, supported by evidence we can actually show.

## Slide 7: Tomorrow’s research starts ahead
**2:50–3:20 (30 seconds)**

*Slow down on 'the work stays'. This is the value transition.*

When that investigation ends, the work stays. Profiles retain notes and source records. Shortlists and research stages organize the next steps. Exports let someone take the findings into another workflow. Underneath, SQLite persistence, backups, and resumable jobs support continued use. We also implemented a role-based team adapter and a documented API. Those are foundations for reuse and maintenance. Public deployment and larger-scale operation still need validation.

## Slide 8: AI interprets retained evidence
**3:20–4:00 (40 seconds)**

*Explain the sequence in plain language. Keep the local experiment limitation audible.*

AI fits into that memory. First, retrieve relevant saved evidence. Then give the model a bounded context and check its returned references. Cloud mode supports question planning and answers. We also tested a small local model on this eight-gigabyte laptop. One fictional-evidence test took about twelve seconds, then unloaded. It also misread evidence. So we label it experimental, show sources, and keep human review central. Reference validation catches unsupported citations; it cannot guarantee that an interpretation is true.

## Slide 9: We measured the retrieval
**4:00–4:35 (35 seconds)**

*Emphasize 'synthetic' and 'characters'. Do not imply measured token savings.*

We tested the retrieval itself. Across four synthetic scenarios, it returned the exact expected result sets in all four. In the office-prospect case, it selected 2,549 context characters instead of 14,897, about 83 percent fewer. That demonstrates focused retrieval, not measured token savings or revenue impact. The next benchmark needs Reece’s judgment: are the organizations relevant, and is the evidence useful enough for a real next step?

## Slide 10: The next conversation starts informed
**4:35–5:00 (25 seconds)**

*Return to Reece. End cleanly, then stop speaking.*

So return to Reece’s laptop. He has a place to find organizations, inspect what supports a match, and retain the research for the next conversation. Our next step is a small pilot with him, reviewing twenty offices and districts and measuring relevance and research time. Pittsburgh IQ gives that pilot a working foundation. The value we want to prove is simple: less repeated searching, and more useful local business relationships.

## Delivery notes

Use the screenshots as your demo so the five-minute story does not depend on network access or a model loading live. Speak to the judges rather than reading the slide. Pause after the opening question and before the final sentence.

If you fall behind, shorten slide 7 after “another workflow” and slide 8 after “central.” Keep the client problem, evidence walkthrough, and honest evaluation limits.

## Judge questions to prepare for

- **What does AI actually do?** Optional structured query planning and interpretation over retrieved evidence. Citation checks validate reference IDs, not truth. The small local model is a test mode.
- **What makes this useful to Vicall?** A focused shortlist with inspectable website findings, contacts and retained research. Client value is a hypothesis to validate in the proposed pilot.
- **What scales?** Persistent records, bounded research jobs, an API and a role-based shared-workspace adapter. Production hosting, larger datasets and real-world evaluation remain.
- **What does 83% mean?** One synthetic office-prospect scenario used 2,549 of 14,897 context characters. It is not measured token or cost savings.

## Rubric coverage

1. Problem and solution fit: slides 1–3, client feedback and initial segments.
2. Value to the client: slides 4–7 and 10, inspectable findings and retained work.
3. Sustainability: slide 7, persistence, recovery, team/API foundations; deployment limits in narration.
4. Effective use of AI: slides 8–9, grounded context, reference validation, local test and bounded evaluation.
5. Presentation and communication: ten visual slides, a single client story, five-minute timed script.