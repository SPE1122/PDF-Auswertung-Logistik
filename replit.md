# PDF Auswertung Logistik

## Overview
A Streamlit-based web application for analyzing logistics PDF loading plans. Users upload a PDF file and the app extracts component data (Bauteile), truck/trailer assignments (Pritschen), and weights, then generates a filterable summary with Excel export.

## Project Architecture
- **Language**: Python 3.12
- **Framework**: Streamlit
- **Key Libraries**: pdfplumber (PDF parsing), pandas (data processing), xlsxwriter (Excel export)
- **Entry Point**: `app.py`

## How to Run
```
streamlit run app.py --server.port 5000 --server.address 0.0.0.0 --server.headless true
```

## Project Structure
- `app.py` — Main application (UI + PDF parsing logic)
- `requirements.txt` — Python dependencies

## Recent Changes
- 2026-02-07: Initial setup in Replit environment, configured Streamlit to run on port 5000
