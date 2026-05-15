import { useCallback, useEffect, useMemo, useState } from "react";
import { apiJson, invalidateCache, peekCache } from "../lib/api.js";
import "../styles/claude-usage.css";
import AppHeader from "../components/AppHeader.jsx";
import AppFooter from "../components/AppFooter.jsx";
import LoadingDots from "../components/LoadingDots.jsx";

const TEAM_USAGE_PATH = "/api/team-usage";
const CACHE_TTL_MS = 5 * 60 * 1000;

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

function ProviderLabel({ type }) {
  const labels = { claude_oauth: "Claude", codex: "Codex", cursor: "Cursor", copilot: "Copilot", openai_api: "OpenAI", anthropic_api: "Anthropic API" };
  return <span className="sub-provider-name">{labels[type] ?? type}</span>;
}

function CodexSubscription({ sub }) {
  const reset5h = timeUntil(sub.five_hour?.resets_at);
  const reset7d = timeUntil(sub.seven_day?.resets_at);

  if (sub.status !== "ok") {
    return (
      <div className="sub-block sub-block-muted">
        <div className="sub-head">
          <ProviderLabel type="codex" />
          <span className="sub-tier">{sub.tier}</span>
          <StatusDot status={sub.status} />
        </div>
        <p className="sub-status-msg">
          {sub.status === "not_configured" ? "Not configured" : sub.status}
        </p>
        {sub.hint && <code className="sub-hint">{sub.hint}</code>}
      </div>
    );
  }

  return (
    <div className="sub-block">
      <div className="sub-head">
        <ProviderLabel type="codex" />
        <span className="sub-tier">{sub.tier}</span>
        <StatusDot status="ok" />
      </div>
      <div className="sub-metric">
        <span className="sub-metric-label">5h{reset5h ? <> · resets {reset5h}</> : null}</span>
        <UsageBar utilization={sub.five_hour?.utilization} />
      </div>
      <div className="sub-metric">
        <span className="sub-metric-label">7d{reset7d ? <> · resets {reset7d}</> : null}</span>
        <UsageBar utilization={sub.seven_day?.utilization} />
      </div>
      {sub.quota_status !== "ok" && (
        <p className="sub-status-msg">
          Live quota unavailable: {sub.quota_status}
          {sub.quota_hint ? ` (${sub.quota_hint})` : ""}
        </p>
      )}
    </div>
  );
}

function StatusDot({ status }) {
  const cls = status === "ok" ? "status-dot ok" : status === "not_configured" ? "status-dot unconfigured" : "status-dot error";
  return <span className={cls} />;
}

function ClaudeSubscription({ sub }) {
  const reset5h = timeUntil(sub.five_hour?.resets_at);
  const reset7d = timeUntil(sub.seven_day?.resets_at);

  if (sub.status !== "ok") {
    return (
      <div className="sub-block sub-block-muted">
        <div className="sub-head">
          <ProviderLabel type={sub.type} />
          <span className="sub-tier">{sub.tier}</span>
          <StatusDot status={sub.status} />
        </div>
        <p className="sub-status-msg">
          {sub.status === "not_configured" ? "Not configured" :
           sub.status === "token_expired" ? "Token expired" :
           sub.status === "timeout" ? "Request timed out" :
           sub.status}
        </p>
        {sub.hint && <code className="sub-hint">{sub.hint}</code>}
      </div>
    );
  }

  return (
    <div className="sub-block">
      <div className="sub-head">
        <ProviderLabel type={sub.type} />
        <span className="sub-tier">{sub.tier}</span>
        <StatusDot status="ok" />
      </div>
      <div className="sub-metric">
        <span className="sub-metric-label">5h{reset5h ? <> · resets {reset5h}</> : null}</span>
        <UsageBar utilization={sub.five_hour?.utilization} />
      </div>
      <div className="sub-metric">
        <span className="sub-metric-label">7d{reset7d ? <> · resets {reset7d}</> : null}</span>
        <UsageBar utilization={sub.seven_day?.utilization} />
      </div>
    </div>
  );
}

function CursorSubscription({ sub }) {
  const cycleEndStr = sub.billing_cycle_end ? new Date(parseInt(sub.billing_cycle_end)).toISOString() : null;
  const resetBilling = timeUntil(cycleEndStr);

  if (sub.status !== "ok") {
    return (
      <div className="sub-block sub-block-muted">
        <div className="sub-head">
          <ProviderLabel type="cursor" />
          <span className="sub-tier">{sub.tier}</span>
          <StatusDot status={sub.status} />
        </div>
        <p className="sub-status-msg">
          {sub.status === "not_configured" ? "Not configured" :
           sub.status === "token_expired" ? "Token expired" :
           sub.status === "timeout" ? "Request timed out" :
           sub.status}
        </p>
        {sub.hint && <code className="sub-hint">{sub.hint}</code>}
      </div>
    );
  }

  const { plan_usage } = sub;

  return (
    <div className="sub-block">
      <div className="sub-head">
        <ProviderLabel type="cursor" />
        <span className="sub-tier">{sub.tier}</span>
        <StatusDot status="ok" />
      </div>
      <div className="sub-metric">
        <span className="sub-metric-label">Fast Requests{resetBilling ? <> · resets {resetBilling}</> : null}</span>
        <UsageBar utilization={plan_usage?.auto_percent} />
      </div>
      <div className="sub-metric">
        <span className="sub-metric-label">API Models</span>
        <UsageBar utilization={plan_usage?.api_percent} />
      </div>
    </div>
  );
}

function MemberCard({ member, loading }) {
  const initials = member.name?.charAt(0)?.toUpperCase() ?? "?";
  const subs = member.subscriptions ?? [];

  return (
    <div className="member-card">
      <div className="member-header">
        <div className="member-avatar">{initials}</div>
        <div className="member-meta">
          <span className="member-name">{member.name}</span>
          <span className="member-role">{member.role}</span>
        </div>
      </div>

      {loading && subs.length === 0 ? (
        <div className="sub-block sub-block-loading"><LoadingDots /></div>
      ) : subs.length === 0 ? (
        <div className="sub-block sub-block-muted"><p className="sub-status-msg">No subscriptions configured</p></div>
      ) : (
        subs.map((sub, i) => {
          if (sub.type === "codex") return <CodexSubscription key={i} sub={sub} />;
          if (sub.type === "cursor") return <CursorSubscription key={i} sub={sub} />;
          return <ClaudeSubscription key={i} sub={sub} />;
        })
      )}
    </div>
  );
}

function OrgApiCard({ api }) {
  return (
    <div className="org-api-card">
      <div className="sub-head">
        <ProviderLabel type={api.type} />
        <span className="sub-tier">{api.label}</span>
        <StatusDot status={api.status} />
      </div>
      {api.status !== "ok" && (
        <p className="sub-status-msg">
          {api.status === "not_configured" ? "Not configured" : api.status}
        </p>
      )}
    </div>
  );
}

export default function ClaudeUsage() {
  useEffect(() => { document.title = "XC Gradient — AI Usage"; }, []);

  const initialData = useMemo(() => peekCache(TEAM_USAGE_PATH), []);
  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(!initialData);
  const [errorMsg, setErrorMsg] = useState("");

  const refresh = useCallback(async ({ forceNetwork = false, silent = false } = {}) => {
    if (forceNetwork) invalidateCache(TEAM_USAGE_PATH);
    if (!silent) setLoading(true);
    setErrorMsg("");
    try {
      const result = await apiJson(TEAM_USAGE_PATH, { timeoutMs: 20000, cacheTtlMs: CACHE_TTL_MS });
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
    const id = setInterval(() => refresh({ silent: true }), CACHE_TTL_MS);
    return () => clearInterval(id);
  }, [initialData, refresh]);

  const members = data?.members ?? [];
  const orgApis = (data?.org_apis ?? []).filter(a => a.status !== "not_configured");

  return (
    <>
      <AppHeader subtitle="AI Usage" />

      <main className="team-usage-main">
        <div className="usage-head">
          <div>
            <p className="internal-kicker">Monitoring</p>
            <h1 className="usage-title">AI Usage</h1>
            {data && (
              <p className="usage-meta">
                <span>{members.length} members</span>
                <span className="usage-sep">·</span>
                <span>checked {timeSince(data.last_refreshed)}</span>
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

        <div className="member-grid">
          {loading && members.length === 0 ? (
            Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="member-card member-card-skeleton">
                <div className="member-header">
                  <div className="member-avatar member-avatar-skeleton" />
                  <div className="member-meta">
                    <span className="skeleton-line skeleton-line-name" />
                    <span className="skeleton-line skeleton-line-role" />
                  </div>
                </div>
                <div className="sub-block sub-block-loading"><LoadingDots /></div>
              </div>
            ))
          ) : (
            members.map(m => <MemberCard key={m.id} member={m} loading={loading} />)
          )}
        </div>

        {orgApis.length > 0 && (
          <section className="org-apis-section">
            <h2 className="org-apis-heading">Org APIs</h2>
            <div className="org-apis-grid">
              {orgApis.map((api, i) => <OrgApiCard key={i} api={api} />)}
            </div>
          </section>
        )}
      </main>

      <AppFooter left="Internal · XC Gradient · AI Usage" right="Auto-refreshes every 5 min" />
    </>
  );
}
