# Loom recording guide (about 7–10 minutes)

Record the actual application and your own explanation. Do not claim functionality or testing you have not personally checked. Never show `.env` or your API key on screen.

1. **0:00–0:45 — Problem and architecture.** “This application converts the ten workflows supplied in Excel into a shared execution system. One LLM identifies the workflow and extracts inputs; one engine executes reviewed tool steps.” Show the README diagram.
2. **0:45–1:45 — Excel source.** Open both workbook sheets. Explain the eight workflow fields and supplied test questions. Show the catalog loader and one entry of `definitions.json`. Explain the source-drift check and why prose is bound into reviewed executable steps rather than blindly executed.
3. **1:45–2:45 — Routing and tools.** Show `LiveLLM.select`: catalog prompt, `execute_workflow` schema, forced tool call, validated ID/confidence. Show `Engine.run`: merge inputs, required-field checks, shared registry dispatch, trace and final output. Give a short selection justification; no need to discuss hidden chain-of-thought.
4. **2:45–4:30 — Live working examples.** Start `python -m agent --mode live serve`. Confirm the visible live-mode badge. Run inventory, pricing, order lookup and product generation. Show final data and trace. Explain that order/shipment APIs are simulated but the LLM call is real. If asked, calculations run in Python, not in the LLM.
5. **4:30–5:30 — Conditions and errors.** Show campaign request without goal/dates → `needs_input`; add fields and rerun. Show unknown order. Show vendor invalid rows. Show task assignment with `required_skills: ["cobol"]` → escalation. Explain transient retries versus permanent failures.
6. **5:30–6:30 — Cover all ten.** Run `python -m agent --mode live examples` and inspect saved results. In the UI, briefly show duplicates, keyword CSV output and performance metrics. Explain exactly 10% versus above 10% boundaries.
7. **6:30–7:30 — Tests and workflow 11.** Run `python -m unittest discover -s tests -v`. Show the extension test: new Excel row and reviewed definition reuse existing tools without changing engine/router/UI. A genuinely new business capability needs a new reusable tool.
8. **7:30–8:30 — Decisions and limitations.** Explain why a compact custom framework fits the assignment; why no ten chatbots; why deterministic calculations; why simulation; why human review of generated prose. Explain the local demo server and what you would add for production.

Before recording: run all ten workflows with your actual key, inspect generated content, check tests and commit the final examples. Replace any inaccurate claims in README with your actual validation status.

## Interview questions to rehearse

- What does the Excel file control? What does the executable configuration add?
- Why not let the LLM calculate reorder quantities or percentages?
- What is a tool call? Where does the selected tool get executed?
- How do missing fields differ from execution errors?
- What happens at exactly 10% variance or failure rate?
- How do you prevent missing product attributes being invented?
- How do you match an email with several orders?
- What happens if every suitable employee is at capacity?
- What changes for workflow 11? What changes for a real order API?
- What was tested offline, with mocks, and with a live LLM?

## Final submission format

```text
GitHub: https://github.com/YOUR_USERNAME/YOUR_REPOSITORY
Loom: https://www.loom.com/share/YOUR_RECORDING
```

These are placeholders. Submit your real accessible links only.
