"use client";
import { useState } from "react";

/* eslint-disable @typescript-eslint/no-explicit-any */
type A = any;
const EMPTY: A = { name: "", students: "", team_size: "", staff: "", guests: "", duration_hours: "", start_hour: "", budget: "",
  prayer_minutes: "", lunch_minutes: "", venues: [], food: [], judging: {}, extras: {}, rules: {}, notes: [] };

const Num = ({ label, hint, v, on }: { label: string; hint: string; v: A; on: (x: A) => void }) => (
  <label className="fld"><span>{label}</span><small>{hint}</small>
    <input type="number" value={v ?? ""} onChange={e => on(e.target.value === "" ? "" : Number(e.target.value))} /></label>
);

export default function Setup({ api, hack, onSaved }: { api: (p: string, o?: RequestInit) => Promise<A>; hack: string; onSaved: (id: string) => void }) {
  const [c, setC] = useState<A>(EMPTY);
  const [text, setText] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: A) => setC((p: A) => ({ ...p, [k]: v }));
  const sub = (g: string, k: string, v: A) => setC((p: A) => ({ ...p, [g]: { ...p[g], [k]: v } }));
  const row = (g: string, i: number, k: string, v: A) => set(g, c[g].map((x: A, j: number) => (j === i ? { ...x, [k]: v } : x)));
  const fail = (e: A) => setMsg("Error: " + e.message);
  const json = (b: A, method = "POST") => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) });

  async function analyse() {
    setBusy(true); setMsg("Reading your description...");
    try { setC({ ...EMPTY, ...(await api("/setup/from-text", json({ text }))) }); setMsg("Filled in below. Check it, then save."); }
    catch (e) { fail(e); }
    setBusy(false);
  }
  async function load() {
    if (hack === "default") return setMsg("The default hackathon has no saved setup.");
    try { setC({ ...EMPTY, ...(await api(`/hackathons/${hack}/config`)) }); setMsg("Loaded."); } catch (e) { fail(e); }
  }
  async function save(asNew: boolean) {
    setBusy(true); setMsg("Saving and planning...");
    try {
      const r = asNew ? await api("/hackathons", json(c)) : await api(`/hackathons/${hack}/config`, json(c, "PUT"));
      setMsg("Saved. Run outcome: " + (r.run?.outcome ?? "ok")); onSaved(asNew ? r.id : hack);
    } catch (e) { fail(e); }
    setBusy(false);
  }

  return (
    <div className="stack">
      <div className="card"><h3>Describe it in words (optional)</h3>
        <textarea placeholder="e.g. 200 students in teams of 4, 5 hours from 9am, budget Rs 800,000. Hall A seats 250 for Rs 120,000 with a generator..." value={text} onChange={e => setText(e.target.value)} />
        <div className="row"><button disabled={busy || !text.trim()} onClick={analyse}>Fill the form with AI</button>
          <button disabled={busy} onClick={load}>Load saved setup</button></div></div>
      <div className="card"><h3>1. Basics</h3><label className="fld"><span>Hackathon name</span><input value={c.name} onChange={e => set("name", e.target.value)} /></label>
        <div className="fields">
          <Num label="Students" hint="people competing" v={c.students} on={x => set("students", x)} />
          <Num label="Team size" hint="max students per team (team limit)" v={c.team_size} on={x => set("team_size", x)} />
          <Num label="Staff" hint="organisers and helpers" v={c.staff} on={x => set("staff", x)} />
          <Num label="Extra guests" hint="seated and fed, not students" v={c.guests} on={x => set("guests", x)} />
        </div></div>
      <div className="card"><h3>2. Time and money</h3><div className="fields">
        <Num label="Duration (hours)" hint="total length of the event" v={c.duration_hours} on={x => set("duration_hours", x)} />
        <Num label="Start hour" hint="24h clock, e.g. 10" v={c.start_hour} on={x => set("start_hour", x)} />
        <Num label="Prayer break (min)" hint="must fit in the schedule" v={c.prayer_minutes} on={x => set("prayer_minutes", x)} />
        <Num label="Lunch break (min)" hint="blank = 30 assumed" v={c.lunch_minutes} on={x => set("lunch_minutes", x)} />
        <Num label="Total budget (Rs)" hint="the plan may never exceed this" v={c.budget} on={x => set("budget", x)} /></div></div>
      <div className="card"><h3>3. Venues (seats)</h3>
        {c.venues.map((v: A, i: number) => (
          <div className="row" key={i}>
            <input placeholder="Name" value={v.name ?? ""} onChange={e => row("venues", i, "name", e.target.value)} />
            <input type="number" placeholder="Seats" value={v.capacity ?? ""} onChange={e => row("venues", i, "capacity", Number(e.target.value))} />
            <input type="number" placeholder="Price Rs" value={v.price ?? ""} onChange={e => row("venues", i, "price", Number(e.target.value))} />
            <label className="chk"><input type="checkbox" checked={!!v.generator} onChange={e => row("venues", i, "generator", e.target.checked)} />Generator</label>
            <button onClick={() => set("venues", c.venues.filter((_: A, j: number) => j !== i))}>Remove</button></div>))}
        <button onClick={() => set("venues", [...c.venues, { name: "", capacity: "", price: "", generator: false }])}>+ Add venue</button></div>
      <div className="card"><h3>4. Food packages</h3>
        {c.food.map((v: A, i: number) => (
          <div className="row" key={i}>
            <input placeholder="Package name" value={v.name ?? ""} onChange={e => row("food", i, "name", e.target.value)} />
            <input type="number" placeholder="Price per person Rs" value={v.price ?? ""} onChange={e => row("food", i, "price", Number(e.target.value))} />
            <button onClick={() => set("food", c.food.filter((_: A, j: number) => j !== i))}>Remove</button></div>))}
        <button onClick={() => set("food", [...c.food, { name: "", price: "" }])}>+ Add package</button></div>
      <div className="card"><h3>5. Judging and rubric</h3><div className="fields">
        <Num label="Judges" hint="how many judges" v={c.judging.count} on={x => sub("judging", "count", x)} />
        <Num label="Fee per judge (Rs)" hint="honorarium" v={c.judging.honorarium} on={x => sub("judging", "honorarium", x)} />
        <Num label="Minutes per team" hint="time to judge one team" v={c.judging.minutes_per_team} on={x => sub("judging", "minutes_per_team", x)} />
        <Num label="Max teams per judge" hint="workload cap" v={c.judging.max_teams_per_judge} on={x => sub("judging", "max_teams_per_judge", x)} />
        <Num label="Minimum judges" hint="rule: at least this many" v={c.judging.min_judges} on={x => sub("judging", "min_judges", x)} /></div></div>
      <div className="card"><h3>6. Other costs</h3>
        {Object.entries(c.extras).map(([k, v]: A) => (
          <div className="row" key={k}><input value={k} readOnly /><input type="number" value={v}
            onChange={e => set("extras", { ...c.extras, [k]: Number(e.target.value) })} />
            <button onClick={() => { const { [k]: _, ...rest } = c.extras; set("extras", rest); }}>Remove</button></div>))}
        <div className="row"><button onClick={() => { const n = prompt("Cost name (e.g. prizes, printing)"); if (n) set("extras", { ...c.extras, [n]: 0 }); }}>+ Add cost</button></div></div>
      <div className="card"><h3>7. Rules</h3><div className="fields">
        <Num label="Max venue price (Rs)" hint="no dearer venue" v={c.rules.max_venue_price} on={x => sub("rules", "max_venue_price", x)} />
        <Num label="Max food per person (Rs)" hint="no dearer package" v={c.rules.max_food_price} on={x => sub("rules", "max_food_price", x)} />
        <Num label="Venue closing hour" hint="24h, event must end before" v={c.rules.closing_hour} on={x => sub("rules", "closing_hour", x)} /></div>
        <label className="chk"><input type="checkbox" checked={!!c.rules.requires_generator} onChange={e => sub("rules", "requires_generator", e.target.checked)} />Venue must have a generator</label>
        <label className="fld"><span>Other rules (one per line, shown as notes)</span>
          <textarea value={c.notes.join("\n")} onChange={e => set("notes", e.target.value.split("\n").filter(Boolean))} /></label></div>
      <div className="row"><button disabled={busy || !c.name.trim()} onClick={() => save(true)}>Create as new hackathon</button>
        <button disabled={busy || hack === "default"} onClick={() => save(false)}>Update selected hackathon</button></div>
      <div className="err">{msg}</div>
    </div>
  );
}
