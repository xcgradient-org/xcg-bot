import { useCallback, useEffect, useMemo, useState } from "react";
import { apiJson, invalidateCache, peekCache } from "../lib/api.js";
import "../styles/claude-usage.css";
import AppHeader from "../components/AppHeader.jsx";
import AppFooter from "../components/AppFooter.jsx";
import LoadingDots from "../components/LoadingDots.jsx";

function timeUntil(iso) {
  if (!iso) return null;
  const diff = Math.max(0, new Date(iso) - Date.now());
  const totalMins = Math.floor(diff / 60000);
  const days = Math.floor(totalMins / 1440);
  const hours = Math.floor((totalMins % 1440) / 60);
  const mins = totalMins % 60;
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
}

function timeSince(iso) {
  if (!iso) return "—";
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return "just now";
  const mins = Math.floor(diff / 60);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ago`;
}

function barColor(pct) {
  if (pct >= 90) return "var(--danger)";
  if (pct >= 70) return "var(--warn)";
  return "var(--accent)";
}

function UsageBar({ utilization }) {
  const raw = utilization ?? 0;
  const color = barColor(raw);
  return (
    <div className="usage-bar-wrap">
      <div className="usage-bar-track">
        <div className="usage-bar-fill" style={{ width: `${raw}%`, background: color }} />
      </div>
      <span className="usage-bar-pct" style={{ color }}>{Math.round(raw)}%</span>
    </div>
  );
}

function MetricCard({ label, window: win, sublabel }) {
  if (!win) return null;
  const reset = timeUntil(win.resets_at);
  return (
    <div className="usage-metric-card">
      <div className="usage-metric-head">
        <span className="usage-metric-label">{label}</span>
        {reset && <span className="usage-metric-reset">resets in {reset}</span>}
      </div>
      <UsageBar utilization={win.utilization} />
      {sublabel && <span className="usage-metric-sub">{sublabel}</span>}
    </div>
  );
}

const CLAUDE_USAGE_PATH = "/api/claude-usage";
const CLAUDE_USAGE_TTL_MS = 5 * 60 * 1000;

export default function ClaudeUsage() {
  useEffect(() => { document.title = "XC Gradient — Claude Usage"; }, []);

  const initialData = useMemo(() => peekCache(CLAUDE_USAGE_PATH), []);
  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(!initialData);
  const [errorMsg, setErrorMsg] = useState("");

  const refresh = useCallback(async ({ forceNetwork = false, silent = false } = {}) => {
    if (forceNetwork) invalidateCache(CLAUDE_USAGE_PATH);
    if (!silent) setLoading(true);
    setErrorMsg("");
    try {
      const result = await apiJson(CLAUDE_USAGE_PATH, { timeoutMs: 15000, cacheTtlMs: CLAUDE_USAGE_TTL_MS });
      if (result.error) {
        setErrorMsg(result.hint || result.error);
      } else {
        setData(result);
      }
    } catch (exc) {
      setErrorMsg(exc.message || "Failed to fetch usage");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh({ silent: Boolean(initialData) });
    const id = setInterval(() => refresh({ silent: true }), 5 * 60 * 1000);
    return () => clearInterval(id);
  }, [initialData, refresh]);

  const sonnetSub =
    data?.seven_day_sonnet?.utilization > 0
      ? `Sonnet ${Math.round(data.seven_day_sonnet.utilization)}% · resets ${timeUntil(data.seven_day_sonnet.resets_at)}`
      : null;

  return (
    <>
      <AppHeader subtitle="Claude Usage" />

      <main className="usage-main">
        <div className="usage-head">
          <div>
            <p className="internal-kicker">Subscription quota</p>
            <h1 className="usage-title">Claude Usage</h1>
            {data && (
              <p className="usage-meta">
                <span className="usage-profile">{data.profile}</span>
                <span className="usage-sep">·</span>
                <span>{data.subscription_type}</span>
                <span className="usage-sep">·</span>
                <span>checked {timeSince(data.last_checked)}</span>
              </p>
            )}
          </div>
          <button className="btn btn-secondary usage-refresh" onClick={() => refresh({ forceNetwork: true })}>
            {loading ? <>Refreshing <LoadingDots /></> : "Refresh"}
          </button>
        </div>

        {errorMsg && (
          <div className="inline-error usage-error">
            <strong>Unable to load.</strong> {errorMsg}
          </div>
        )}

        <div className="usage-grid">
          {loading && !data ? (
            <>
              <div className="usage-metric-card is-loading"><LoadingDots /></div>
              <div className="usage-metric-card is-loading"><LoadingDots /></div>
            </>
          ) : (
            <>
              <MetricCard label="5-hour window" window={data?.five_hour} />
              <MetricCard label="Weekly (7-day)" window={data?.seven_day} sublabel={sonnetSub} />
            </>
          )}
        </div>
      </main>

      <AppFooter left="Internal · XC Gradient · Claude Usage" right="Auto-refreshes every 5 min" />
    </>
  );
}
