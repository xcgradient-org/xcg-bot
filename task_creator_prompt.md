# XC Gradient — Weekly Task Creator

Single-file HTML internal tool. Three co-founders (Oriol/CEO, Arnau/CTO, Adam/COO) use it once a week to plan tasks for the following week. It replaces the Discord `/tasks add` command for bulk weekly planning — tens of tasks at a time, not one or two.

---

## Flow

Three sequential phases. User cannot skip forward.

### Phase 1 — Configure

Three things to fill before continuing:

1. **Founder** — pick one: Oriol (CEO), Arnau (CTO), Adam (COO)
2. **Project** — dropdown. On load, fetch `GET /api/projects` → `{ projects: [{ id, name }] }`. If fetch fails, use three hardcoded mock projects so the UI stays clickable.
3. **Target week** — text input, pre-filled with next ISO week code (`YY-WNN` format, e.g. `25-W21`). Button to reset to computed next week. User can type a custom value.

### Phase 2 — Paste & Parse

Large textarea. User pastes anything — bullets, numbered lists, prose, one task per line.

Button triggers `POST /api/parse`:
```
Request:  { founder, role, text, week_code }
Response: { descriptions: ["Task one.", "Task two.", ...] }
```

If fetch fails: parse client-side — split by newlines, strip bullet/number prefixes, capitalize, add trailing period. This keeps the page fully demoable without a server.

Show loading state during request. Show error only if fetch fails AND client-side fallback produces nothing.

### Phase 3 — Review & Push

Editable task list. Each task:
- Inline editable (auto-resize textarea)
- Individually deletable
- Add blank task button
- Running count visible

**Notion ID preview block** — fetch `POST /api/preview-ids`:
```
Request:  { founder, role, project_id, project_name, week_code, count }
Response: { ids: ["PROJ-CEO-5", "PROJ-CEO-6", ...] }
```
If fetch fails: generate mock IDs client-side. Show each ID next to its task description.

**Push button** — `POST /api/tasks`:
```
Request:  { founder, role, project_id, project_name, week_code, descriptions: [...] }
Response: { created: N }
```
Show success confirmation. If fetch fails because backend is offline, show a "demo mode" message instead of an error (not a failure, just offline).

User can go back to Phase 2 (re-parse) or Phase 1 (start over) at any time without losing config.

---

## Technical constraints

- Single HTML file — all CSS and JS inline, no external dependencies, no framework
- Every `fetch()` has a client-side fallback so the page works without a server
- Loading, success, and error states for every async action
- Current week code visible somewhere persistent (header or badge)
- Auto-resizing textareas on Phase 3

---

## Design

Full freedom. Pick a visual direction and commit to it. Should feel like a tool a real startup would use internally — intentional and specific, not a generic template.
