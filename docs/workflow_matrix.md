# Workflow interpretation

The original Excel workbook is unchanged. Definitions are reviewed executable bindings, not an unvalidated LLM-generated program.

## WF001 — Inventory Restock Check

- **Trigger**: User asks which products need restocking
- **Inputs**: Product inventory CSV; minimum stock threshold
- **Steps**: Load inventory → compare current stock with minimum threshold → identify low-stock products → calculate reorder quantity → generate restock list
- **Decision Logic**: If current_stock < minimum_stock, mark product for restock
- **Tools Required**: CSV reader; calculator
- **Expected Output**: List of products requiring restock with current stock, threshold, and suggested reorder quantity

## WF002 — Product Price Validation

- **Trigger**: User asks to validate product prices
- **Inputs**: Product CSV; vendor price list
- **Steps**: Load product prices → match products by SKU → compare internal and vendor prices → calculate percentage difference → flag exceptions
- **Decision Logic**: Flag when price difference exceeds 10%
- **Tools Required**: CSV reader; calculator
- **Expected Output**: Validation report showing matched products, price differences, and exceptions

## WF003 — Vendor File Processing

- **Trigger**: User provides a vendor file for processing
- **Inputs**: CSV/XLSX file containing vendor product data
- **Steps**: Read file → detect columns → normalize column names → validate required fields → identify invalid rows → produce cleaned dataset
- **Decision Logic**: Rows missing SKU or product name are invalid
- **Tools Required**: Excel/CSV parser; data validation
- **Expected Output**: Cleaned file plus validation summary and invalid-row report

## WF004 — Product Description Generator

- **Trigger**: User asks to generate product content
- **Inputs**: Product name; category; attributes; material; color; target audience
- **Steps**: Validate required attributes → create product description → generate short description → generate SEO title → generate meta description
- **Decision Logic**: Do not invent missing product attributes; explicitly mark missing information
- **Tools Required**: LLM; text validation
- **Expected Output**: Product description, short description, SEO title, and meta description

## WF005 — Customer Order Status

- **Trigger**: User asks for an order status
- **Inputs**: Order ID or customer email
- **Steps**: Validate identifier → search order data → retrieve order status → retrieve shipment information → summarize current status
- **Decision Logic**: If no order is found, ask for another identifier
- **Tools Required**: Order database/API; shipment lookup
- **Expected Output**: Order status, items, shipment status, and tracking information when available

## WF006 — Duplicate Product Detection

- **Trigger**: User asks to find duplicate products
- **Inputs**: Product catalog
- **Steps**: Load products → normalize names/SKUs → compare identifiers → compare product attributes → group likely duplicates → assign confidence
- **Decision Logic**: Exact SKU match is a definite duplicate; high attribute similarity is a possible duplicate
- **Tools Required**: CSV/database reader; text similarity
- **Expected Output**: Duplicate groups with matching fields and confidence level

## WF007 — Marketing Campaign Brief

- **Trigger**: User asks to create a campaign brief
- **Inputs**: Campaign goal; product list; target audience; promotion; dates
- **Steps**: Validate inputs → identify campaign objective → summarize products → create messaging → create channel recommendations → create campaign checklist
- **Decision Logic**: If campaign goal or dates are missing, request them before generating the brief
- **Tools Required**: LLM; product data reader
- **Expected Output**: Structured campaign brief with objective, audience, messaging, channels, timeline, and checklist

## WF008 — SEO Keyword Classification

- **Trigger**: User uploads or provides a keyword list
- **Inputs**: Keyword CSV; product/category information
- **Steps**: Read keywords → remove duplicates → classify search intent → map keywords to categories → identify high-priority keywords → export results
- **Decision Logic**: Classify each keyword as informational, commercial, transactional, or navigational
- **Tools Required**: CSV reader; LLM/classifier
- **Expected Output**: Keyword report with intent, category, priority, and recommended target page

## WF009 — Employee Task Assignment

- **Trigger**: Manager asks the agent to assign a task
- **Inputs**: Task description; employee list; skills; workload; priority; deadline
- **Steps**: Understand task requirements → compare employee skills → check current workload → rank candidates → select employee → generate assignment summary
- **Decision Logic**: Prefer employees with required skills and available capacity; escalate if no suitable employee exists
- **Tools Required**: Employee/task database; ranking logic
- **Expected Output**: Recommended employee, reasoning, priority, deadline, and task summary

## WF010 — Workflow Performance Report

- **Trigger**: User asks for a performance report
- **Inputs**: Workflow execution logs
- **Steps**: Load execution logs → calculate success/failure rate → calculate average execution time → identify frequent errors → identify slow steps → generate recommendations
- **Decision Logic**: Flag workflows with failure rate above 10% or average execution time above defined threshold
- **Tools Required**: CSV/database reader; calculator; reporting
- **Expected Output**: Performance summary with metrics, problem areas, and improvement recommendations