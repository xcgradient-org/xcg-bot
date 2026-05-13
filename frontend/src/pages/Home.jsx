import { useEffect, useState } from "react";
import { apiJson, invalidateCache, peekCache, postJson } from "../lib/api.js";
import AppHeader from "../components/AppHeader.jsx";
import AppFooter from "../components/AppFooter.jsx";
import { ROUTES } from "../lib/routes.js";


function WeekSwitcher() {
  const initialWeek = peekCache("/api/current-week");
  const [week, setWeek] = useState(initialWeek);
  const [weekLoading, setWeekLoading] = useState(!initialWeek);
  const [state, setState] = useState("idle");
  const [message, setMessage] = useState("");

  async function loadWeek() {
    try {
      if (!week) setWeekLoading(true);
      setWeek(await apiJson("/api/current-week", { timeoutMs: 12000, cacheTtlMs: 10 * 60 * 1000 }));
    } catch (exc) {
      setMessage(exc.message || "Week unavailable");
    } finally {
      setWeekLoading(false);
    }
  }

  async function switchWeek() {
    if (!week || state === "loading") return;
    setState("loading");
    setMessage("");
    try {
      const result = await postJson("/api/week/rollover", { current_week: week.current_week }, { timeoutMs: 90000 });
      invalidateCache("/api/current-week");
      setWeek({ current_week: result.to_week, next_week: result.to_week });
      setState("success");
      setMessage(`Moved ${result.moved_count} task${result.moved_count === 1 ? "" : "s"}`);
      window.setTimeout(() => setState("idle"), 2600);
    } catch (exc) {
      setState("error");
      setMessage(exc.message || "Rollover failed");
    }
  }

  useEffect(() => {
    loadWeek();
  }, []);

  return (
    <div className={`week-switcher is-${state}`}>
      <button className="week-chip" type="button" onClick={loadWeek} title="Refresh current week">
        <span>Current week</span>
        {week?.current_week ? (
          <b>{week.current_week}</b>
        ) : (
          <span className={`skeleton-pill ${weekLoading ? "is-loading" : ""}`} aria-hidden="true" />
        )}
      </button>
      <button className="week-next-btn" type="button" disabled={!week || state === "loading"} onClick={switchWeek}>
        {state === "loading" ? "Switching..." : state === "success" ? "Success" : "Go to next week!"}
      </button>
      {message ? <span className="week-message">{message}</span> : null}
    </div>
  );
}

function DailyLogPanel() {
  const initialStatus = peekCache("/api/logging/status");
  const [status, setStatus] = useState(initialStatus);
  const [statusLoading, setStatusLoading] = useState(!initialStatus);
  const [loadingFounder, setLoadingFounder] = useState("");
  const [message, setMessage] = useState("");

  async function loadStatus() {
    try {
      if (!status) setStatusLoading(true);
      const next = await apiJson("/api/logging/status", { timeoutMs: 12000, cacheTtlMs: 2 * 60 * 1000 });
      setStatus(next);
    } catch (exc) {
      setMessage(exc.message || "Log status unavailable");
    } finally {
      setStatusLoading(false);
    }
  }

  async function logNow(founder) {
    if (loadingFounder) return;
    setLoadingFounder(founder);
    setMessage("");
    try {
      const result = await postJson("/api/logging/log-now", { founder }, { timeoutMs: 20000 });
      invalidateCache("/api/logging/status");
      await loadStatus();
      if (result.created) {
        setMessage(`${result.founder.name} logged at ${result.logged_at || "--:--"}`);
      } else if (result.reason === "already_logged") {
        setMessage(`${result.founder.name} already logged at ${result.logged_at || "--:--"}`);
      } else if (result.reason === "no_completed_tasks") {
        setMessage(`${result.founder.name} has no completed tasks yet`);
      } else {
        setMessage("Log unavailable");
      }
    } catch (exc) {
      setMessage(exc.message || "Log failed");
    } finally {
      setLoadingFounder("");
    }
  }

  useEffect(() => {
    loadStatus();
  }, []);

  return (
    <div className="daily-log-panel">
      <div className="daily-log-head">
        <span>Log day</span>
        {status?.today_iso ? (
          <b>{status.today_iso}</b>
        ) : (
          <span className={`skeleton-pill ${statusLoading ? "is-loading" : ""}`} aria-hidden="true" />
        )}
      </div>
      <div className="daily-log-founders">
        {status?.founders?.length ? (
          status.founders.map((founder) => (
            <button
              className={`daily-log-btn ${founder.logged ? "is-logged" : ""}`}
              key={founder.founder}
              type="button"
              disabled={Boolean(loadingFounder) || founder.logged}
              onClick={() => logNow(founder.founder)}
              title={founder.logged ? `${founder.founder_name} logged at ${founder.logged_at}` : `Log ${founder.founder_name}`}
            >
              <span>{founder.role}</span>
              <b>{founder.logged ? `Logged ${founder.logged_at || ""}` : loadingFounder === founder.founder ? "Logging..." : "Log now"}</b>
            </button>
          ))
        ) : (
          <>
            <span className={`daily-log-btn skeleton-btn ${statusLoading ? "is-loading" : ""}`} aria-hidden="true" />
            <span className={`daily-log-btn skeleton-btn ${statusLoading ? "is-loading" : ""}`} aria-hidden="true" />
          </>
        )}
      </div>
      {message ? <span className="week-message">{message}</span> : null}
    </div>
  );
}

export default function Home() {
  useEffect(() => { document.title = "XC Gradient — Internal"; }, []);
  return (
    <>
      <AppHeader subtitle="Internal" />

      <main className="internal-home">
        <div className="page-top-bar">
          <WeekSwitcher />
          <DailyLogPanel />
        </div>
        <section className="internal-home-head">
          <p className="internal-kicker">Internal OS</p>
          <h1>XC Gradient command center</h1>
          <p>Shared tools for turning planning notes into Notion records and managing the active operating week.</p>
        </section>

        <section className="tool-grid" aria-label="Available tools">
          {ROUTES.map(({ path, cardMeta, cardEyebrow, cardTitle, cardDescription }) => (
            <a className="tool-card" href={path} key={path}>
              <span className="tool-meta">{cardMeta}</span>
              <span className="tool-eyebrow">{cardEyebrow}</span>
              <strong>{cardTitle}</strong>
              <span>{cardDescription}</span>
            </a>
          ))}
        </section>
      </main>

      <AppFooter left="Internal · XC Gradient · React" right="Cloudflare Access ready" />
    </>
  );
}
