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
streamlit run app.py
```

## Project Structure
- `app.py` — Main application (UI + PDF parsing logic)
- `requirements.txt` — Python dependencies
- `.streamlit/config.toml` — Streamlit configuration

## Recent Changes
- 2026-02-07: Initial setup in Replit environment
- 2026-02-07: Configured Streamlit for deployment and cleaned up requirements.txt
