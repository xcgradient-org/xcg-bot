import { useEffect, useState } from "react";
import { apiJson, postJson } from "../lib/api.js";

const tools = [
  {
    href: "/task-creator",
    eyebrow: "Weekly execution",
    title: "Task Creator",
    description: "Parse founder task notes, reserve Notion IDs, and push weekly tasks.",
    meta: "Tasks",
  },
  {
    href: "/okr-creator",
    eyebrow: "Strategy",
    title: "OKR Creator",
    description: "Create objectives and measurable key results in the Notion OKR databases.",
    meta: "Objectives",
  },
  {
    href: "/meeting-creator",
    eyebrow: "Cadence",
    title: "Meeting Creator",
    description: "Schedule a meeting, write it to Notion, and announce it in Discord.",
    meta: "Meetings",
  },
];

function WeekSwitcher() {
  const [week, setWeek] = useState(null);
  const [state, setState] = useState("idle");
  const [message, setMessage] = useState("");

  async function loadWeek() {
    try {
      setWeek(await apiJson("/api/current-week", { timeoutMs: 12000 }));
    } catch (exc) {
      setMessage(exc.message || "Week unavailable");
    }
  }

  async function switchWeek() {
    if (!week || state === "loading") return;
    setState("loading");
    setMessage("");
    try {
      const result = await postJson("/api/week/rollover", { current_week: week.current_week }, { timeoutMs: 90000 });
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
        <b>{week?.current_week || "--"}</b>
      </button>
      <button className="week-next-btn" type="button" disabled={!week || state === "loading"} onClick={switchWeek}>
        {state === "loading" ? "Switching..." : state === "success" ? "Success" : "Go to next week!"}
      </button>
      {message ? <span className="week-message">{message}</span> : null}
    </div>
  );
}

function DailyLogPanel() {
  const [status, setStatus] = useState(null);
  const [loadingFounder, setLoadingFounder] = useState("");
  const [message, setMessage] = useState("");

  async function loadStatus() {
    try {
      const next = await apiJson("/api/logging/status", { timeoutMs: 12000 });
      setStatus(next);
    } catch (exc) {
      setMessage(exc.message || "Log status unavailable");
    }
  }

  async function logNow(founder) {
    if (loadingFounder) return;
    setLoadingFounder(founder);
    setMessage("");
    try {
      const result = await postJson("/api/logging/log-now", { founder }, { timeoutMs: 20000 });
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
        <b>{status?.today_iso || "--"}</b>
      </div>
      <div className="daily-log-founders">
        {(status?.founders || []).map((founder) => (
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
        ))}
      </div>
      {message ? <span className="week-message">{message}</span> : null}
    </div>
  );
}

export default function Home() {
  document.title = "XC Gradient — Internal";
  return (
    <>
      <header className="bar internal-home-bar">
        <div className="bar-inner">
          <div className="wordmark">
            <span className="dot" />
            <span>XC&nbsp;Gradient</span>
            <span className="sep">/</span>
            <span className="sub">Internal</span>
          </div>
          <nav className="internal-home-nav" aria-label="Internal tools">
            <a href="/task-creator">Tasks</a>
            <a href="/okr-creator">OKRs</a>
            <a href="/meeting-creator">Meetings</a>
          </nav>
          <div className="internal-status">
            <WeekSwitcher />
            <DailyLogPanel />
          </div>
        </div>
      </header>

      <main className="internal-home">
        <section className="internal-home-head">
          <p className="internal-kicker">Internal OS</p>
          <h1>XC Gradient command center</h1>
          <p>Shared tools for turning planning notes into Notion records and managing the active operating week.</p>
        </section>

        <section className="tool-grid" aria-label="Available tools">
          {tools.map((tool) => (
            <a className="tool-card" href={tool.href} key={tool.href}>
              <span className="tool-meta">{tool.meta}</span>
              <span className="tool-eyebrow">{tool.eyebrow}</span>
              <strong>{tool.title}</strong>
              <span>{tool.description}</span>
            </a>
          ))}
        </section>
      </main>

      <footer className="foot">
        <span>Internal · XC Gradient · React</span>
        <span>Cloudflare Access ready</span>
      </footer>
    </>
  );
}
