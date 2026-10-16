# Pittsburgh IQ: five-minute presentation script

Team: Rayane El Yasti, Oleg Hartman, Alexander Kearney, Noah White.

Target: 5:00 including slide changes and pauses. Rehearse using the checkpoints below. The narration also appears in PowerPoint speaker notes.

## Slide 1: Pittsburgh IQ
**0:00–0:20 (20 seconds)**

*Introduce the team, then move directly into the challenge.*

A local business can offer an excellent service and still be difficult to discover. Pittsburgh IQ gives people a place to research local organizations and decide what to investigate next. We are Rayane El Yasti, Oleg Hartman, Alexander Kearney, and Noah White, from Duquesne University.

## Slide 2: The challenge
**0:20–0:55 (35 seconds)**

*State the brief clearly. Connect discovery to a real business decision.*

The challenge asked us to use AI to turn scattered local business information into actionable research. For Vicall, that means finding organizations that could benefit from website and SEO services. The broader opportunity includes finding suppliers and business partners. Our response combines a searchable directory with a research assistant. The question guiding the product is simple: what does someone need to know before starting a useful business conversation?

## Slide 3: A prospect list is only the beginning
**0:55–1:30 (35 seconds)**

*Tell this as an illustrative scenario, not an actual customer story.*

Picture a small digital agency looking for its next customer. It finds a local office, opens the website, searches for a contact, and writes down a possible issue. Then someone asks: where did that information come from? Is it current? Has a teammate checked it already? A list of names cannot answer those questions. Our product keeps the organization, its evidence, and the next research step together, so the next person can continue the investigation.

## Slide 4: A working directory of Pittsburgh
**1:30–2:10 (40 seconds)**

*Point to the screenshot, then the figures. Do not read every label.*

The story starts with a working directory of 2,603 Pittsburgh business candidates. Our saved snapshot includes 1,059 listed websites and 146 email contacts. A researcher can narrow that starting point by neighborhood, category, and available information. These are public listings that still need review. An empty website field is a gap in our data, rather than proof that a business has no website. The directory gives the agency a research starting point, with uncertainty visible from the beginning.

## Slide 5: A question leads to inspectable evidence
**2:10–2:45 (35 seconds)**

*Point to the result and its dated references.*

Now the researcher asks a question. In this captured example, a search for legal services returned 22 candidates using saved evidence, with no new external page requests. A result includes public contact references, source links, and observation dates. The purpose can change from finding a provider to researching prospects or partners. The system also identifies gaps, such as an unreviewed decision-maker role. That makes follow-up research specific, and gives a teammate something they can check.

## Slide 6: A website finding gives the conversation context
**2:45–3:25 (40 seconds)**

*Show the saved check, then explain what the agency can do next.*

For the agency, the next step is website research. Website Lab saves the URL, response, observation time, and technical findings. A missing heading, for example, creates a concrete question to investigate before outreach. Failed or blocked requests remain inconclusive. The score describes a static technical checklist and does not measure Google rankings. The researcher can then save notes, organize a shortlist, and export the findings. The intended value is less repeated searching and a better prepared conversation. A client pilot still needs to measure that value.

## Slide 7: AI works with the research already collected
**3:25–4:00 (35 seconds)**

*Explain the sequence without jargon. Keep the limitation brief and clear.*

The AI workflow begins with relevant saved records. Retrieval selects a focused evidence set, an optional model interprets it, and the application checks the references it returns. Users can inspect the sources behind the answer. We also tested a small local model on an eight-gigabyte laptop, with one response taking about twelve seconds. It misread part of the evidence, so local AI remains experimental. Checking citations helps trace an answer, while human review remains necessary to judge its meaning.

## Slide 8: Focused retrieval, measured
**4:00–4:35 (35 seconds)**

*Emphasize what the test measured and keep the boundary clear.*

We evaluated retrieval with four synthetic scenarios. All four returned the exact expected result sets. In the office-prospect scenario, the system selected 2,549 context characters from a full set of 14,897. That is about 83 percent less text for the model to consider. This measures the retrieval mechanism on a small fictional test set. It does not establish real-world prospect quality or token savings. Our next benchmark will use client-reviewed organizations and measure relevance alongside actual research time.

## Slide 9: Research that the next person can continue
**4:35–5:00 (25 seconds)**

*Return to the agency story and finish cleanly.*

The agency now has a place to find organizations, inspect evidence, and keep what it learns. SQLite storage, backups, resumable jobs, and an API provide foundations for continued use. Next comes a focused pilot with twenty offices and school districts. Pittsburgh IQ turns a starting list into research that the next person can continue, helping local businesses prepare for better conversations.

## Delivery notes

The agency story is illustrative. Use the screenshots for a predictable presentation within five minutes. Pause briefly after the three research questions. Keep the synthetic-test and experimental-AI qualifications audible.

## Questions to prepare for

- **Why would someone use it?** To narrow organizations, inspect dated evidence, and preserve research for a teammate or later session. The proposed pilot will measure relevance and research time.
- **What does AI contribute?** Optional query planning and interpretation over retrieved evidence, followed by checks of cited business and evidence IDs. Reference validation does not guarantee a correct interpretation.
- **What does 83% mean?** The office-prospect test selected 2,549 of 14,897 characters. It measures context reduction on fictional data, not token savings or model answer accuracy.
- **What remains?** Broader client evaluation, reviewed decision-maker roles, rendered browser checks, and production deployment validation.

## Rubric coverage

Problem and solution fit: slides 2–3. Client value: slides 4–6. Sustainability: slide 9. AI depth and evaluation: slides 7–8. Communication: a single research story, with a five-minute timed delivery.