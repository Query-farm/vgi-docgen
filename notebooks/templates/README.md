# Synthetic order-summary template

`order_summary.docx` is an original notebook companion authored with python-docx.
Its six required variables are `customer_id`, `customer`, `gross_text`,
`discount_pct_text`, `discount_text`, and `net_text`.
All calculation and decimal formatting happen in visible SQL. The worker receives
strings and renders them unchanged; this template does no arithmetic.

Paragraphs contain the synthetic customer ID/name, currency/scope, gross USD,
discount percentage/amount and net USD. The notebook compares these paragraphs
against SQL results in both individual and merged documents. This checks content,
not Word/LibreOffice pagination or visual fidelity. No PDF conversion is requested.
