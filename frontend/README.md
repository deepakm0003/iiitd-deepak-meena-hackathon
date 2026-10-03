# Tripwire web

Marketing site and dashboard. React + Vite + TypeScript, Tailwind CSS v4, Framer Motion.

```
npm install
npm run dev      # http://localhost:5173, proxies /api/* to the FastAPI engine on :8000
npm run build
```

The landing page replays the recorded Western Alliance trace (`src/lib/caseStudy.ts`, from
`tests/golden/western_alliance.json`); the dashboard under `/app` reads the live API.
