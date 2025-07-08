#  AI-Powered Invoice Splitter & Metadata Extractor

This Python script uses **Gemini Pro (Google Generative AI)** to intelligently detect and extract metadata from PDFs or images containing **multiple invoices**, then splits and saves each invoice into separate files, along with structured metadata stored in **MongoDB**.

---

##  Features

-  AI-powered invoice detection (Gemini 1.5 Pro)
-  Splits multi-invoice PDFs into individual invoice files
-  Supports image files: `.jpg`, `.jpeg`, `.png`
-  Extracts metadata:
  - Invoice number
  - Page range (PDFs)
  - Invoice type (e.g. GST, Proforma, Tax)
  - Hotel name
-  Stores metadata in MongoDB (`all_invoices` collection)
-  Skips PDFs with ≤ 2 pages (assumed already split)
- Supports basic image splitting (top/bottom halves if multiple invoices)

