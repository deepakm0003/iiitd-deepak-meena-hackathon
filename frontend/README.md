# Tripwire web

Marketing site and dashboard. React + Vite + TypeScript, Tailwind CSS v4, Framer Motion.

```
npm install
npm run dev      # http://localhost:5173, proxies /api/* to the FastAPI engine on :8000
npm run build
```

The landing page replays the recorded Western Alliance trace (`src/lib/caseStudy.ts`, from
`tests/golden/western_alliance.json`). The dashboard under `/app` (signals, reasoning trace, portfolio and
stress tests, watchlist, model trust, data sources) reads the live API, so start it first from the repo root:

```
python -m uvicorn tripwire.api.app:create_app --factory --port 8000
```
