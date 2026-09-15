# OptiStock AI — Agentic Stockout Resolution System

This folder contains the complete project code for the OptiStock AI - multi-agent stockout resolution system.

## Quick Start

### 1. Setup Environment

Create and activate a virtual environment:

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**Linux/macOS:**
```bash
python -m venv venv
source venv/bin/activate
```

Install dependencies:
```bash
python -m pip install -r requirements.txt
```

Create your `.env` file (copy from `.env.example`):
```bash
cp .env.example .env
```
Ensure `OPENAI_API_KEY` is set in the `.env` file.

### 2. Prepare Database

If you haven't already, seed the SQLite database with the provided seed data:
```bash
python database/seed.py
```

### 3. Run the System

The application comes with an interactive Streamlit UI. Run the app using:
```bash
streamlit run app.py
```

## Running Tests

The test suite covers all required acceptance scenarios plus failure paths. It uses mock LLM agents and tools so that tests are deterministic, fast, and cost nothing.

```bash
pytest tests/ -v
```

## Architecture

The system uses **LangGraph** to coordinate 3 LLM agents (Investigation, Sourcing, Review) and 5 deterministic nodes (Input Validation, Draft Proposal, Prepare Approval, Revalidation, Execution). State is maintained via LangGraph's checkpointer, enabling the system to pause execution during the human approval step and resume flawlessly.

See `design.md` for a complete architecture breakdown, agent charters, tool permissions, and design rationale.
