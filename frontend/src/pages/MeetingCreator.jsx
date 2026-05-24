import { useEffect, useMemo, useState } from "react";
import { apiJson, postJson } from "../lib/api.js";
import AppHeader from "../components/AppHeader.jsx";
import AppFooter from "../components/AppFooter.jsx";
import LoadingDots from "../components/LoadingDots.jsx";

const founders = [
  { id: "oriol", name: "Oriol", role: "CEO", avatar: "OR" },
  { id: "arnau", name: "Arnau", role: "CTO", avatar: "AR" },
  { id: "adam", name: "Adam", role: "COO", avatar: "AD" },
];

function weekCode(date = new Date()) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const week = Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
  return `${String(d.getUTCFullYear()).slice(-2)}-W${String(week).padStart(2, "0")}`;
}

function titleSuggestion(type) {
  if (type === "Weekly Sync") return `Weekly Sync - ${weekCode()}`;
  return type || "Meeting";
}

export default function MeetingCreator() {
  useEffect(() => { document.title = "XC Gradient — Meeting Creator"; }, []);
  const [phase, setPhase] = useState(1);
  const [owners, setOwners] = useState([]);
  const [meetingTypes, setMeetingTypes] = useState([]);
  const [typesLoading, setTypesLoading] = useState(true);
  const [typesError, setTypesError] = useState("");
  const [type, setType] = useState("");
  const [mode, setMode] = useState("online");
  const [title, setTitle] = useState(titleSuggestion(""));
  const [dateInput, setDateInput] = useState("");
  const [notes, setNotes] = useState("");
  const [meetingLink, setMeetingLink] = useState("");
  const [address, setAddress] = useState("");
  const [parsed, setParsed] = useState(null);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState(true);

  const defaultType = meetingTypes[0] || "";
  const selectedAttendees = owners.map((owner) => owner.role);
  const primaryOwner = owners[0] || null;
  const canContinue = owners.length > 0 && type && mode && !typesLoading && meetingTypes.length > 0;
  const canParse = Boolean(primaryOwner && title.trim() && dateInput.trim() && (mode === "online" ? meetingLink.trim() : address.trim()));
  const target = useMemo(() => parsed?.date_label || dateInput || "Unscheduled", [parsed, dateInput]);

  useEffect(() => {
    loadMeetingTypes();
  }, []);

  function changeType(nextType) {
    setType(nextType);
    setTitle(titleSuggestion(nextType));
  }

  async function loadMeetingTypes() {
    setTypesLoading(true);
    setTypesError("");
    try {
      const payload = await apiJson("/api/meetings/types", { timeoutMs: 12000 });
      const nextTypes = Array.isArray(payload.types)
        ? payload.types.map((item) => String(item || "").trim()).filter(Boolean)
        : [];
      if (!nextTypes.length) {
        throw new Error("No meeting types returned from Notion.");
      }
      const nextType = nextTypes.includes(type) && type ? type : nextTypes[0];
      setMeetingTypes(nextTypes);
      setType(nextType);
      if (!type || !nextTypes.includes(type)) {
        setTitle(titleSuggestion(nextType));
      }
      setOnline(true);
    } catch (exc) {
      setOnline(false);
      setTypesError(exc.message || "Could not load meeting types.");
    } finally {
      setTypesLoading(false);
    }
  }

  function toggleOwner(owner) {
    setOwners((current) => {
      if (current.some((item) => item.id === owner.id)) {
        return current.filter((item) => item.id !== owner.id);
      }
      return [...current, owner];
    });
  }

  async function parseMeeting() {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const payload = await postJson("/api/meetings/parse", {
        founder: primaryOwner.id,
        role: primaryOwner.role,
        title,
        date_input: dateInput,
        type,
        attendees: selectedAttendees,
        location: mode === "online" ? "Online" : "In Person",
        notes,
        meeting_link: mode === "online" ? meetingLink : "",
        address: mode === "in-person" ? address : "",
      }, { timeoutMs: 25000 });
      setParsed(payload.meeting);
      setOnline(true);
      setPhase(3);
    } catch (exc) {
      setOnline(false);
      setError(exc.message || "Could not parse the meeting.");
    } finally {
      setBusy(false);
    }
  }

  async function pushMeeting() {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const payload = await postJson("/api/meetings", {
        founder: primaryOwner.id,
        role: primaryOwner.role,
        meeting: parsed,
      }, { timeoutMs: 60000 });
      setResult(payload);
      setOnline(true);
    } catch (exc) {
      setOnline(false);
      setError(exc.message || "Could not create the meeting.");
    } finally {
      setBusy(false);
    }
  }

  function startOver() {
    setPhase(1);
    setOwners([]);
    setType(defaultType);
    setMode("online");
    setTitle(titleSuggestion(defaultType));
    setDateInput("");
    setNotes("");
    setMeetingLink("");
    setAddress("");
    setParsed(null);
    setError("");
    setResult(null);
  }

  return (
    <>
      <AppHeader subtitle="Meeting Creator" />

      <main>
        <div className="page-top-bar">
          <nav className="stepper">
            {[["01", "Configure"], ["02", "Details"], ["03", "Review"]].map(([num, label], index) => {
              const step = index + 1;
              return (
                <span className={`step ${phase === step ? "is-active" : ""} ${phase > step ? "is-done" : ""}`} key={num}>
                  <span className="num"><span>{num}</span></span><span>{label}</span>
                </span>
              );
            })}
          </nav>
          <div className="meeting-pill">
            <span className={`conn ${online ? "is-online" : "is-offline"}`}><span className="dot" />{online ? "Live" : "Check"}</span>
            <span className="label">Target</span>
            <span className="code">{target}</span>
          </div>
        </div>
        <section className={`phase ${phase === 1 ? "is-active" : ""}`}>
          <div className="phase-head">
            <h1><span className="num">01</span>Configure the meeting</h1>
            <div className="blurb">Pick owners, type, and whether the meeting is online or in person.</div>
          </div>

          <div className="field">
            <div className="field-label"><span className="name">Owners</span><span className="req">required</span><span className="help">Selected owners are the attendees.</span></div>
            <div className="founders">
              {founders.map((item) => (
                <button className={`founder ${owners.some((owner) => owner.id === item.id) ? "is-selected" : ""}`} type="button" key={item.id} onClick={() => toggleOwner(item)}>
                  <span className="avatar">{item.avatar}</span>
                  <span className="name">{item.name}</span>
                  <span className="role">{item.role}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="field">
            <div className="field-label"><span className="name">Type</span><span className="req">required</span></div>
            {typesLoading ? (
              <div className="seg" aria-live="polite">
                <button className="is-active" type="button" disabled>Loading <LoadingDots /></button>
              </div>
            ) : typesError ? (
              <div className="inline-error">
                {typesError}
                <button className="btn btn-secondary" type="button" onClick={loadMeetingTypes}>Retry</button>
              </div>
            ) : (
              <div className="seg">
                {meetingTypes.map((item) => (
                  <button className={type === item ? "is-active" : ""} type="button" key={item} onClick={() => changeType(item)}>{item}</button>
                ))}
              </div>
            )}
          </div>

          <div className="field">
            <div className="field-label"><span className="name">Mode</span><span className="req">required</span></div>
            <div className="seg mode-seg">
              <button className={mode === "online" ? "is-active" : ""} type="button" onClick={() => setMode("online")}>Online</button>
              <button className={mode === "in-person" ? "is-active" : ""} type="button" onClick={() => setMode("in-person")}>In person</button>
            </div>
          </div>

          <div className="cta-row">
            <div />
            <button className="btn btn-primary" type="button" disabled={!canContinue} onClick={() => setPhase(2)}>Continue to details<span className="arrow">-&gt;</span></button>
          </div>
        </section>

        <section className={`phase ${phase === 2 ? "is-active" : ""}`}>
          <div className="phase-head">
            <h1><span className="num">02</span>{mode === "online" ? "Online details" : "In-person details"}</h1>
            <div className="blurb">{mode === "online" ? "Add the call URL and timing." : "Add the physical location and timing."}</div>
          </div>

          <div className="meeting-grid">
            <label className="field meeting-wide">
              <span className="field-label"><span className="name">Title</span><span className="req">required</span></span>
              <input className="input" value={title} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label className="field">
              <span className="field-label"><span className="name">Date and time</span><span className="req">required</span></span>
              <input className="input" placeholder="10:00, 5pm, tomorrow 10:00" value={dateInput} onChange={(event) => setDateInput(event.target.value)} />
            </label>
            {mode === "online" ? (
              <label className="field">
                <span className="field-label"><span className="name">Meeting URL</span><span className="req">required</span></span>
                <input className="input" placeholder="https://meet.google.com/..." value={meetingLink} onChange={(event) => setMeetingLink(event.target.value)} />
              </label>
            ) : (
              <label className="field">
                <span className="field-label"><span className="name">Location</span><span className="req">required</span></span>
                <input className="input" placeholder="Office, client address, room..." value={address} onChange={(event) => setAddress(event.target.value)} />
              </label>
            )}
            <label className="field meeting-wide">
              <span className="field-label"><span className="name">Overview</span><span className="opt">optional</span></span>
              <textarea className="paste" value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Agenda, context, or decision needed." />
            </label>
          </div>

          {error ? <div className="inline-error">{error}</div> : null}

          <div className="cta-row">
            <button className="btn btn-secondary" type="button" onClick={() => setPhase(1)}>Back</button>
            <button className="btn btn-primary" type="button" disabled={!canParse || busy} onClick={parseMeeting}>
              {busy ? <>Preparing <LoadingDots /></> : <>Review meeting<span className="arrow">-&gt;</span></>}
            </button>
          </div>
        </section>

        <section className={`phase ${phase === 3 ? "is-active" : ""}`}>
          <div className="phase-head">
            <h1><span className="num">03</span>Review and announce</h1>
            <div className="blurb">This will create the Notion meeting, attendee tasks, and Discord announcement.</div>
          </div>

          {parsed ? (
            <div className="meeting-review">
              <h2>{parsed.title}</h2>
              <dl>
                <dt>Date</dt><dd>{parsed.date_label}</dd>
                <dt>Type</dt><dd>{parsed.type}</dd>
                <dt>Attendees</dt><dd>{parsed.attendees.join(", ")}</dd>
                <dt>Location</dt><dd>{parsed.location}</dd>
                <dt>Mode</dt><dd>{parsed.mode}</dd>
                <dt>Meeting link</dt><dd>{parsed.meeting_link || "-"}</dd>
                <dt>Address</dt><dd>{parsed.address || "-"}</dd>
                <dt>Overview</dt><dd>{parsed.notes_enhanced || "-"}</dd>
              </dl>
            </div>
          ) : null}

          {error ? <div className="inline-error">{error}</div> : null}
          {result ? (
            <div className="confirmation">
              <div className="checkmark">✓</div>
              <div>
                <h3>Meeting created.</h3>
                <p>Notion page created{result.announced ? " and Discord announcement posted." : ", but Discord announcement did not complete."}</p>
                <p>{result.attendance_tasks_created || 0} attendance task{result.attendance_tasks_created === 1 ? "" : "s"} created.</p>
                {result.attendance_task_error ? <p className="confirm-warning">Attendance task error: {result.attendance_task_error}</p> : null}
              </div>
            </div>
          ) : null}

          <div className="cta-row">
            <div className="meeting-actions">
              <button className="btn btn-secondary" type="button" onClick={() => setPhase(2)}>Back</button>
              <button className="btn btn-secondary" type="button" onClick={startOver}>Start over</button>
            </div>
            <button className="btn btn-accent" type="button" disabled={!parsed || busy || !!result} onClick={pushMeeting}>
              {busy ? <>Creating <LoadingDots /></> : "Create and announce"}
            </button>
          </div>
        </section>
      </main>

      <AppFooter left="Internal · XC Gradient · v0.1" right="Notion + Discord" />
    </>
  );
}
