# What Webvory wants, in plain language

The company wants evidence that you can build an AI automation application, not just prompt ChatGPT. A user writes a request, an agent identifies one of the supplied business workflows, Python executes its tools in the right order, business decisions are applied, and the application displays the selected workflow, steps and final result.

They are evaluating requirement interpretation, reusable architecture, workflow selection, LLM/tool integration, validation/error handling, tests and your ability to explain the code yourself. They explicitly allow AI assistance, but you remain responsible for reviewing, testing and understanding it.

The original file has two sheets: `Workflows` contains the ten definitions; `Test_Questions` gives ten example user requests and what the evaluator intends to check.

## What you must submit

Only two links: one accessible GitHub repository and one Loom video showing the actual running application. Everything needed to reproduce the application belongs in the repository, including the original Excel file. No separate emailed workbook, ZIP or README.

Given the email was shared on Monday 12 October 2026, “Wednesday, 2 pm” most likely means **14 October 2026, 2:00 pm IST**. The email does not give an explicit date or timezone; confirm if there is contrary scheduling information.

## Step-by-step solution

1. **Translate each Excel row into a contract.** Write down its inputs, steps, tools, decisions and expected output. Preserve every important threshold and missing-data instruction.
2. **Prepare realistic sample data.** Inventory, products, vendor prices, vendor files, catalog, keywords, employees, orders/shipments and execution logs. Label APIs/data as simulated.
3. **Load Excel into a workflow catalog.** The agent must actually read the workbook, not merely copy its names into ten unrelated chatbots.
4. **Create reviewed executable definitions.** Map prose steps to registered tool names and their parameters. This is configuration, not a separate chatbot per workflow.
5. **Build one router.** Give the LLM the current catalog and an `execute_workflow` tool schema. It selects an ID, extracts explicitly stated inputs and gives a short selection reason. Ambiguity needs clarification.
6. **Build one executor.** Validate ID and inputs, run named tools in order, record outputs, apply conditions and return a result. The engine should not contain ten workflow-specific branches.
7. **Implement reusable tools.** Readers/parsers, numeric comparisons, SKU matching, content generation, lookups, similarity, ranking, exports and reporting. Keep deterministic rules outside LLM prose generation.
8. **Handle errors intentionally.** Missing goal/dates: ask, not invent. Unknown order: request another ID. Invalid vendor row: report it. No suitable employee: escalate. Temporary API failure: retry within limits. Bad data: show an error.
9. **Make execution visible.** Show selected workflow, a short selection reason, ordered tool steps, step outcomes and final result. Persist run traces for inspection.
10. **Test all ten workflows and edge cases.** Successful routing alone is not enough: check calculation boundaries, missing inputs, invalid rows, absent tracking and escalation. Test LLM integration separately from deterministic tools.
11. **Demonstrate extensibility.** Add a new catalog row plus its reviewed definition, reuse existing tools, and keep the engine unchanged. A new capability may need a new tool.
12. **Document and rehearse.** Provide clear installation commands, example requests/inputs/outputs, environment configuration, decisions and limitations. Run on your own Mac, then record a real demo and explain the architecture in your own words.

## What you need to provide next

- A working LLM API key configured locally. Do not paste it into messages or GitHub.
- A GitHub repository to publish this project. Your known username is `Kirito9988`; the destination repository still needs to be chosen/created.
- Your Loom account/recording, with your own voice and explanation of the running application.

The starter implementation is runnable offline and has all ten workflows. It is not submission-complete until you perform a live LLM run, review the outputs, publish the repository and record the video.
