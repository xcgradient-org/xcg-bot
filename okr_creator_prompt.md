# XC Gradient — OKR Creator

Single-file HTML internal tool. Three co-founders (Oriol/CEO, Arnau/CTO, Adam/COO) use it at the start of a quarter or a year to define their OKRs and push them to Notion. Period can be quarterly or annual.

---

## Flow

Three sequential phases. User cannot skip forward.

### Phase 1 — Configure

Three things to fill before continuing:

1. **Founder** — pick one: Oriol (CEO), Arnau (CTO), Adam (COO)
2. **Period type** — toggle between two modes:
   - **Quarterly** — then pick quarter (Q1 / Q2 / Q3 / Q4) and year
   - **Annual** — then pick year only
3. **Project** (optional) — dropdown. Fetch `GET /api/projects` → `{ projects: [{ id, name }] }`. If fetch fails, use mock data. Can be left blank if OKRs are role-wide rather than project-specific.

Switching between Quarterly and Annual shows/hides the quarter picker. Year defaults to current year.

### Phase 2 — Paste & Parse

Large textarea. User pastes a raw brain-dump of their OKR ideas — could be objectives only, objectives with bullet KRs, freeform goals, anything.

Button triggers `POST /api/okr/parse`:
```
Request:  { founder, role, period_type, quarter, year, text }
Response: {
  objectives: [
    {
      title: "Grow revenue pipeline",
      key_results: [
        { description: "Close 3 enterprise deals", metric: "deals", target: "3" },
        { description: "Reach €500k ARR", metric: "€ ARR", target: "500000" }
      ]
    },
    ...
  ]
}
```

If fetch fails: parse client-side — split by double newlines or numbered items to form objectives; lines indented or preceded by `-` or `•` under each become key results. This keeps the page demoable without a server.

Show loading state during request. Show error only if fetch fails AND client-side fallback produces nothing.

### Phase 3 — Review & Push

Display the structured OKRs as an editable hierarchy. Each **Objective**:
- Title is editable inline
- Deletable
- Has a button to add a blank Key Result under it
- Can be reordered (drag or up/down arrows)

Each **Key Result** under an objective:
- Description editable inline
- Optional metric field (e.g. "€ ARR", "deals", "%") editable inline
- Optional target value editable inline
- Individually deletable

An "Add Objective" button at the bottom adds a blank objective with one blank KR.

Running count visible: e.g. "3 objectives · 9 key results"

**Push button** — `POST /api/okr/push`:
```
Request: {
  founder, role, period_type, quarter, year, project_id, project_name,
  objectives: [
    {
      title: "...",
      key_results: [{ description: "...", metric: "...", target: "..." }]
    }
  ]
}
Response: { objectives_created: 3, key_results_created: 9 }
```

Show success confirmation with counts. If fetch fails because backend is offline, show a "demo mode" message instead of an error.

User can go back to Phase 2 (re-parse) or Phase 1 (start over) at any time without losing config.

---

## Technical constraints

- Single HTML file — all CSS and JS inline, no external dependencies, no framework
- Every `fetch()` has a client-side fallback so the page works without a server
- Loading, success, and error states for every async action
- Selected period (e.g. "Q2 2025" or "Annual 2026") visible somewhere persistent (header or badge)
- Auto-resizing textareas wherever text is edited inline
- The objective → key result hierarchy must be visually clear

---

## Design

Full freedom. Pick a visual direction and commit to it. Should feel like a tool a real startup would use internally — intentional and specific, not a generic template. The hierarchy between objectives and key results should be the main compositional challenge to solve.
