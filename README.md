# Financial Truth Engine

Evidence-grounded reconciliation of declared wealth against submitted documents. The engine never approves or rejects a customer; an analyst decides.

**Status:** Phases 1–6 (foundation, cases and declarations, document pipeline, structured extraction, entity resolution and graph, deterministic reconciliation) are written but only partly run, because dependencies have not been installed. The pure-Python domain logic (classification, mock extraction, entity resolution, evidence linking, reconciliation engine) was run directly and passes (35 tests).

## Layout
- `backend/` FastAPI app (SQLite + graph port)
- `frontend/` React (Vite) app: dashboard, create case, case detail
- `infrastructure/` optional Neo4j compose file
- `synthetic-data/`, `documentation/`

## Run (when ready)
```powershell
.\my-env\Scripts\Activate.ps1
pip install -r backend\requirements.txt
copy .env.example .env
cd backend
pytest
python -m app.seed          # fictional demo case (migrations run automatically)
uvicorn app.main:app --reload
```
API docs: `http://localhost:8000/docs`. Identity is a placeholder: send `X-Actor-Id` and `X-Actor-Role` (`analyst`, `customer`, `admin`); the default is a local analyst.

## Synthetic demo documents
```powershell
python synthetic-data\generate_demo_documents.py      # writes synthetic-data\demo-case\*.pdf + manifest.json
```
Upload them on the Document Upload page (or `POST /cases/{id}/documents`), then run extraction (`POST /cases/{id}/extract` or the Extract buttons) and review facts, with page and source text, on the case page. With `USE_MOCK_BEDROCK=true` (the default) extraction uses a deterministic offline stand-in. To use Amazon Bedrock set `USE_MOCK_BEDROCK=false`, `AWS_REGION` and `BEDROCK_MODEL_ID`, and provide AWS credentials through the standard environment or profile mechanisms, never in source. The gold-standard expectations are in `synthetic-data\gold\extraction_gold.json`.

## Reconciliation
`POST /cases/{id}/reconciliation/run` computes evidence-backed assets, liabilities and net worth, the declared-versus-verified difference, evidence coverage, duplicate adjustments, stale exclusions and a status for every claim, and creates conflicts and next-best-evidence requests. Read them with `GET /cases/{id}/reconciliation`, `/conflicts` and `/evidence-requirements`. Staleness limits and severities are configurable: copy `documentation\reconciliation-policy.example.json`, set `RECONCILIATION_POLICY_PATH`, and optionally pin the evaluation date with `RECONCILIATION_AS_OF_DATE` (the demo documents are dated 31 March 2026 and the default limits treat them as fresh until March 2027). The Financial Profile, Reconciliation and Conflict Review pages show the results.

## Evidence, graph and the first reconciliation check
After extraction, run `POST /cases/{id}/link-evidence` (or the button on the Evidence Graph or Reconciliation page). It resolves entities, links declared claims to evidence, rebuilds the graph and is safe to repeat. Then see `GET /cases/{id}/reconciliation/sale-proceeds` for sale consideration versus observed bank credits (INR 16,00,000 unexplained in the demo), `GET /cases/{id}/graph` and `GET /cases/{id}/evidence`. Weaker entity matches wait for an analyst on the Evidence Graph page. With `GRAPH_BACKEND=memory` the graph lives in process; set `GRAPH_BACKEND=neo4j` and the `NEO4J_*` variables to store it in Neo4j. Scanned PDFs need optional OCR: `pip install -r backend\requirements-ocr.txt`, install the Tesseract binary, and set `DOCUMENT_PROCESSOR_MODE=local_ocr`.
```powershell
cd frontend
npm install
npm run dev
```
Check `http://localhost:8000/health/ready`.

Neo4j is optional: set `GRAPH_BACKEND=neo4j`, fill in the `NEO4J_*` values in `.env`, and start the server (`docker compose -f infrastructure/docker-compose.yml up -d` if Docker is available).
