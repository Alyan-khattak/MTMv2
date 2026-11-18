"use client";

import { useCallback, useEffect, useState } from "react";
import { Send } from "lucide-react";
import Sidebar from "@/components/dashboard/Sidebar";
import Header from "@/components/dashboard/Header";
import pageShell from "@/components/dashboard/PageShell.module.css";
import Setup from "@/components/Setup";
import layout from "./layout.module.css";

/* eslint-disable @typescript-eslint/no-explicit-any */
type A = any;
const money = (n: number) => "Rs " + Number(n).toLocaleString("en-US");
const FILTERS = ["All", "Accepted", "Rejected", "Superseded", "Irrelevant"];

let HACK = "default"; // selected hackathon, sent with every call
async function api(path: string, opts?: RequestInit) {
  const r = await fetch(path + (path.includes("?") ? "&" : "?") + "h=" + encodeURIComponent(HACK), opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || r.statusText);
  return body;
}

const Dot = ({ a }: { a: string }) => <span className="dot" style={{ background: `var(--${a})` }} />;
const Badge = ({ s }: { s: string }) => <span className={`badge ${s}`}>{s}</span>;
const Rows = ({ r }: { r: [string, any][] }) => (
  <table><tbody>{r.map(([k, v]) => <tr key={k}><td>{k}</td><td>{String(v)}</td></tr>)}</tbody></table>
);
const Section = ({ area, title, s, children }: { area: string; title: string; s: A; children: (s: A) => React.ReactNode }) => (
  <div className="card">
    <h3><Dot a={area} />{title}</h3>
    {!s || s.unresolved
      ? <><Badge s="INCOMPLETE" /> {s?.reason || "not planned yet"}</>
      : <>{children(s)}{s.reasons && <p>{s.reasons}</p>}</>}
  </div>
);

function Plan({ data }: { data: A }) {
  const p = data?.plan;
  if (!p) return <div className="card">{data?.rejection ? `Rejected: ${data.rejection.reason}` : "No plan yet."}</div>;
  const { venue: v, food: f, judging: j, schedule: s, budget: b } = p;
  const pct = b && !b.unresolved ? Math.min(100, (b.total / b.limit) * 100) : 0;
  return (
    <div className="grid">
      {data.rejection && <div className="card full"><Badge s="REJECTED" /> Latest change rejected ({data.rejection.message_ids.join(", ")}): {data.rejection.reason}. The plan below is unchanged and still valid.</div>}
      {p.unenforced?.length > 0 && <div className="card full"><h3>Noted, not enforced</h3>
        <Rows r={p.unenforced.map((u: A) => [u.message_id, u.subject || u.key])} /></div>}
      <div className="card full">
        <h3><Dot a="budget" />Budget <Badge s={p.status} /></h3>
        {!b || b.unresolved ? <><Badge s="INCOMPLETE" /> {b?.reason || "not planned yet"}</> : <>
          <div className="bar"><i style={{ width: pct + "%" }} /></div>
          <Rows r={[...Object.entries(b).filter(([k, x]) => typeof x === "number" && !["total", "limit", "remaining"].includes(k))
            .map(([k, x]) => [k.replace(/_/g, " ").replace(/^./, c => c.toUpperCase()), money(x as number)] as [string, A]),
            ["Total", `${money(b.total)} of ${money(b.limit)}`], ["Remaining", money(b.remaining)]]} /></>}
      </div>
      <Section area="venue" title="Venue" s={v}>{v => <Rows r={[["Name", v.name], ["Capacity", v.capacity], ["Price", money(v.price)], ["Generator", v.generator ? "Yes" : "No"]]} />}</Section>
      <Section area="food" title="Food" s={f}>{f => <Rows r={[["Package", f.package], ["Per head", money(f.price_per_person)], ["Headcount", f.headcount], ["Total", money(f.total_cost)]]} />}</Section>
      <Section area="judging" title="Judging" s={j}>{j => <Rows r={[["Judges", j.judge_count], ["Teams", j.teams], ["Max teams per judge", `${j.max_load} / ${j.max_teams_per_judge}`], ["Honorarium", money(j.total_honorarium)]]} />}</Section>
      <Section area="schedule" title="Schedule" s={s}>{s => <Rows r={s.blocks.map((x: A) => [x.time, x.label])} />}</Section>
    </div>
  );
}

function Trace({ data }: { data: A }) {
  if (!data?.runs?.length) return <div className="card">No trace yet.</div>;
  return <div className="stack">{[...data.runs].reverse().map((r: A) => (
    <div key={r.id}>
      <div className="sep">{r.id} · {r.type} · {r.outcome}</div>
      {data.trace.filter((x: A) => x.run_id === r.id).map((x: A, i: number) => (
        <details className="card" key={i}>
          <summary>
            {x.call_number ? `[${x.call_number}]` : "•"} <Dot a={x.area} /><b>{x.area}</b> <Badge s={x.status} />
            {x.total_tokens ? <span>{x.prompt_tokens}+{x.completion_tokens}={x.total_tokens} tokens</span> : null}
          </summary>
          {x.input && <pre>{x.input}</pre>}<pre>{x.output}</pre>
        </details>
      ))}
      <b>TOTAL TOKENS: {r.total_tokens}</b>
    </div>
  ))}</div>;
}

function Messages({ data }: { data: A }) {
  const [filter, setFilter] = useState("All");
  const shown = (data || []).filter((m: A) => filter === "All" || m.status === filter.toUpperCase());
  return (
    <div className="stack">
      <div className="filters">{FILTERS.map(f => <button key={f} className={f === filter ? "on" : ""} onClick={() => setFilter(f)}>{f}</button>)}</div>
      {shown.map((m: A) => (
        <details className="card" key={m.id}>
          <summary><b>{m.id}</b> {m.source} · {m.date} <Badge s={m.status} /></summary>
          <p>{m.text}</p>{m.reason && <p><i>{m.reason}</i></p>}
          {m.facts.map((f: A, i: number) => <div key={i}>{f.key}{f.subject ? ` (${f.subject})` : ""} = {String(f.value)} <Badge s={f.status} /></div>)}
        </details>
      ))}
      {!shown.length && <div className="card">No messages.</div>}
    </div>
  );
}

export default function Home() {
  const [tab, setTab] = useState("Plan");
  const [plan, setPlan] = useState<A>(null);
  const [trace, setTrace] = useState<A>(null);
  const [msgs, setMsgs] = useState<A>([]);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState("");
  const [hacks, setHacks] = useState<A[]>([]);
  const [hack, setHack] = useState("default");
  const [predictText, setPredictText] = useState("");
  const [form, setForm] = useState({ text: "", source: "", channel: "email" });

  const refresh = useCallback(() =>
    Promise.all([api("/plan"), api("/trace"), api("/messages")])
      .then(([p, t, m]) => { setPlan(p); setTrace(t); setMsgs(m); })
      .catch(e => setErr(e.message)), []);
  const loadHacks = useCallback(() => api("/hackathons").then(setHacks).catch(e => setErr(e.message)), []);
  useEffect(() => { loadHacks(); api("/predict").then(p => setPredictText(p.text)).catch(() => {}); }, [loadHacks]);
  useEffect(() => { HACK = hack; refresh(); }, [hack, refresh]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setRunning(true); setErr("");
    try {
      await api("/message", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
      setForm({ ...form, text: "" });
    } catch (x: A) { setErr(x.message); }
    setRunning(false); refresh();
  }

  async function upload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setRunning(true); setErr("");
    try {
      const r = await api("/upload", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: await file.text() }) });
      setErr(`${file.name}: ${r.outcome}`);
    } catch (x: A) { setErr(x.message); }
    setRunning(false); refresh();
  }

  const run = plan?.last_run;
  return (
    <div className={layout.shell}>
      <Sidebar tab={tab} onTab={setTab} />
      <div className={layout.main}>
        <Header title={tab} running={running} />
        <div className={pageShell.content}>
          <div className="card"><div className="row"><b style={{ whiteSpace: "nowrap", alignSelf: "center" }}>Hackathon</b>
            <select style={{ width: "100%" }} value={hack} onChange={e => setHack(e.target.value)}>
              {hacks.map(h => <option key={h.id} value={h.id}>{h.name}</option>)}</select></div></div>
          <div className="status">{run
            ? <>Last run <b>{run.id}</b> · {run.type} · <Badge s={run.outcome} /> · {run.duration_seconds}s · {run.model_calls} calls · {run.total_tokens} tokens{plan.pending_planners?.length ? " · pending: " + plan.pending_planners.join(", ") : ""}</>
            : "No runs yet. Submit a message or run the CLI."}</div>
          {tab === "Plan" && <div className="card">Prediction for the next change: <b>{predictText}</b></div>}
          {tab === "Plan" && <Plan data={plan} />}
          {tab === "Trace" && <Trace data={trace} />}
          {tab === "Messages" && <Messages data={msgs} />}
          {tab === "Setup" && <Setup api={api} hack={hack} onSaved={id => { loadHacks(); if (id !== hack) setHack(id); else refresh(); }} />}
          {tab !== "Setup" && <div className="card"><h3>Upload a messages file (.txt)</h3>
            <input type="file" accept=".txt,text/plain" disabled={running} onChange={upload} />
            <small>Runs the same way as the command line and checks the plan against every rule.</small></div>}
          {tab !== "Setup" && <form className="card" onSubmit={submit}>
            <textarea placeholder="Paste a new message..." required value={form.text} onChange={e => setForm({ ...form, text: e.target.value })} />
            <div className="row">
              <input placeholder="Source (e.g. Finance)" required value={form.source} onChange={e => setForm({ ...form, source: e.target.value })} />
              <select value={form.channel} onChange={e => setForm({ ...form, channel: e.target.value })}><option>email</option><option>whatsapp</option><option>web</option></select>
              <button id="submit" disabled={running}><Send size={16} /> Submit</button>
            </div>
            <div className="err">{err}</div>
          </form>}
        </div>
      </div>
    </div>
  );
}
