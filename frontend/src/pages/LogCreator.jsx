import { useState } from "react";
import { postJson } from "../lib/api.js";

const founders = [
  { id: "oriol", name: "Oriol", role: "CEO", avatar: "OR" },
  { id: "arnau", name: "Arnau", role: "CTO", avatar: "AR" },
  { id: "adam", name: "Adam", role: "COO", avatar: "AD" },
];

const blockerRoles = ["CEO", "CTO", "COO"];

function LoadingDots() {
  return (
    <span className="loading-dots">
      <span />
      <span />
      <span />
    </span>
  );
}

export default function LogCreator() {
  document.title = "XC Gradient - Log Creator";

  const [phase, setPhase] = useState(1);
  const [founder, setFounder] = useState(null);
  const [preview, setPreview] = useState(null);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [notes, setNotes] = useState("");
  const [blockerEnabled, setBlockerEnabled] = useState(false);
  const [blockerRole, setBlockerRole] = useState("CEO");
  const [blockerMessage, setBlockerMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  async function loadPreview(nextFounder = founder) {
    if (!nextFounder) return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const payload = await postJson(
        "/api/log/preview",
        {
          founder: nextFounder.id,
          role: nextFounder.role,
        },
        { timeoutMs: 45000 },
      );
      setPreview(payload);
      setSelectedIds(new Set(payload.tasks.filter((task) => task.selected).map((task) => task.id)));
      setPhase(2);
    } catch (exc) {
      setError(exc.message || "Could not load log tasks.");
    } finally {
      setBusy(false);
    }
  }

  function chooseFounder(item) {
    setFounder(item);
    loadPreview(item);
  }

  function toggleTask(taskId) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });
  }

  async function saveLog() {
    if (!founder || !preview) return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const payload = await postJson(
        "/api/log",
        {
          founder: founder.id,
          role: founder.role,
          selected_task_ids: Array.from(selectedIds),
          notes,
          blocker: blockerEnabled
            ? {
                target_role: blockerRole,
                message: blockerMessage,
              }
            : null,
        },
        { timeoutMs: 90000 },
      );
      setResult(payload);
      setPhase(3);
    } catch (exc) {
      setError(exc.message || "Could not save log.");
    } finally {
      setBusy(false);
    }
  }

  function startOver() {
    setPhase(1);
    setFounder(null);
    setPreview(null);
    setSelectedIds(new Set());
    setNotes("");
    setBlockerEnabled(false);
    setBlockerRole("CEO");
    setBlockerMessage("");
    setError("");
    setResult(null);
  }

  return (
    <>
      <header className="bar">
        <div className="bar-inner">
          <a className="wordmark" href="/">
            <span className="dot" />
            <span>XC&nbsp;Gradient</span>
            <span className="sep">/</span>
            <span className="sub">Log Creator</span>
          </a>
          <nav className="stepper">
            {[
              ["01", "Founder"],
              ["02", "Log"],
              ["03", "Done"],
            ].map(([num, label], index) => {
              const step = index + 1;
              return (
                <span className={`step ${phase === step ? "is-active" : ""} ${phase > step ? "is-done" : ""}`} key={num}>
                  <span className="num">
                    <span>{num}</span>
                  </span>
                  <span>{label}</span>
                </span>
              );
            })}
          </nav>
          <div className="meeting-pill">
            <a className="home-btn" href="/">
              Home
            </a>
            <span className="conn is-online">
              <span className="dot" />
              Live
            </span>
            <span className="label">Date</span>
            <span className="code">{preview?.today_iso || "--"}</span>
          </div>
        </div>
      </header>

      <main>
        <section className={`phase ${phase === 1 ? "is-active" : ""}`}>
          <div className="phase-head">
            <h1>
              <span className="num">01</span>Choose founder
            </h1>
            <div className="blurb">Load the active task list and today&apos;s completed tasks.</div>
          </div>

          <div className="field">
            <div className="field-label">
              <span className="name">Founder</span>
              <span className="req">required</span>
            </div>
            <div className="founders">
              {founders.map((item) => (
                <button
                  className={`founder ${founder?.id === item.id ? "is-selected" : ""}`}
                  type="button"
                  key={item.id}
                  onClick={() => chooseFounder(item)}
                  disabled={busy}
                >
                  <span className="avatar">{item.avatar}</span>
                  <span className="name">{item.name}</span>
                  <span className="role">{item.role}</span>
                </button>
              ))}
            </div>
          </div>

          {busy ? (
            <div className="confirmation">
              <div className="checkmark">...</div>
              <div>
                Loading tasks <LoadingDots />
              </div>
            </div>
          ) : null}
          {error ? <div className="inline-error">{error}</div> : null}
        </section>

        <section className={`phase ${phase === 2 ? "is-active" : ""}`}>
          <div className="phase-head">
            <h1>
              <span className="num">02</span>Review log
            </h1>
            <div className="blurb">Select the tasks that should count as completed today.</div>
          </div>

          {preview?.already_logged ? (
            <div className="inline-error">
              This founder already logged for {preview.today_iso}. The Discord command also allows one log per business day.
            </div>
          ) : null}

          <div className="summary-strip">
            <span className="chip">
              <span className="k">Founder</span>
              {founder?.name} · {founder?.role}
            </span>
            <span className="chip">
              <span className="k">Week</span>
              {preview?.week_code}
            </span>
            <span className="chip">
              <span className="k">Selected</span>
              {selectedIds.size}
            </span>
          </div>

          <div className="log-task-list">
            {preview?.tasks?.length ? (
              preview.tasks.map((task) => (
                <label className={`log-task ${selectedIds.has(task.id) ? "is-selected" : ""}`} key={task.id}>
                  <input type="checkbox" checked={selectedIds.has(task.id)} onChange={() => toggleTask(task.id)} />
                  <span className="task-id">{task.display_id || "-"}</span>
                  <span>{task.description || "-"}</span>
                </label>
              ))
            ) : (
              <div className="log-empty">No candidate tasks found for this week.</div>
            )}
          </div>

          <label className="field log-notes">
            <span className="field-label">
              <span className="name">Notes</span>
              <span className="opt">optional</span>
            </span>
            <textarea
              className="paste"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="What happened today? Context, decisions, learnings, or loose notes."
            />
          </label>

          <div className="field">
            <label className="log-toggle">
              <input type="checkbox" checked={blockerEnabled} onChange={(event) => setBlockerEnabled(event.target.checked)} />
              <span>Add blocker</span>
            </label>
          </div>

          {blockerEnabled ? (
            <div className="meeting-grid">
              <label className="field">
                <span className="field-label">
                  <span className="name">Owner</span>
                  <span className="req">required</span>
                </span>
                <select className="input" value={blockerRole} onChange={(event) => setBlockerRole(event.target.value)}>
                  {blockerRoles.map((role) => (
                    <option value={role} key={role}>
                      {role}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field meeting-wide">
                <span className="field-label">
                  <span className="name">Blocker</span>
                  <span className="req">required</span>
                </span>
                <textarea
                  className="paste"
                  value={blockerMessage}
                  onChange={(event) => setBlockerMessage(event.target.value)}
                  placeholder="What do you need, and from whom?"
                />
              </label>
            </div>
          ) : null}

          {error ? <div className="inline-error">{error}</div> : null}

          <div className="cta-row">
            <button className="btn btn-secondary" type="button" onClick={startOver}>
              Back
            </button>
            <button
              className="btn btn-accent"
              type="button"
              disabled={busy || preview?.already_logged || (blockerEnabled && !blockerMessage.trim())}
              onClick={saveLog}
            >
              {busy ? (
                <>
                  Saving <LoadingDots />
                </>
              ) : (
                "Save log"
              )}
            </button>
          </div>
        </section>

        <section className={`phase ${phase === 3 ? "is-active" : ""}`}>
          <div className="phase-head">
            <h1>
              <span className="num">03</span>Log saved
            </h1>
            <div className="blurb">Daily log created and selected task completion synced.</div>
          </div>

          {result ? (
            <div className="confirmation">
              <div className="checkmark">✓</div>
              <div>
                <h3>{founder?.name} logged.</h3>
                <p>
                  Tasks done today: <b>{result.completed_count}</b>. Remaining this week:{" "}
                  <b>{result.remaining_count ?? "unavailable"}</b>.
                </p>
                {result.streak ? (
                  <p>
                    Streak: <b>{result.streak}</b>.
                  </p>
                ) : null}
                {result.blocker_posted ? <p>Blocker posted.</p> : null}
              </div>
            </div>
          ) : null}

          <div className="cta-row">
            <a className="btn btn-secondary" href="/">
              Back home
            </a>
            <button className="btn btn-primary" type="button" onClick={startOver}>
              Start another log
            </button>
          </div>
        </section>
      </main>

      <footer className="foot">
        <span>Internal · XC Gradient · Log Creator</span>
        <span>Same daily-log flow as Discord</span>
      </footer>
    </>
  );
}
