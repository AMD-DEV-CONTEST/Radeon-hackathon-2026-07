import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import styles from "./WorkflowPage.module.css";

type Json = Record<string, any>;
async function api(path: string, body?: object): Promise<any> {
  const response = await fetch(path, body === undefined ? undefined : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.message ?? "Request failed");
  return result;
}

export function WorkflowPage({ tasksOnly = false }: { tasksOnly?: boolean }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [events, setEvents] = useState<Json[]>([]);
  const [event, setEvent] = useState<Json | null>(null);
  const [analysis, setAnalysis] = useState<Json | null>(null);
  const [task, setTask] = useState<Json | null>(null);
  const [timeline, setTimeline] = useState<Json[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const listed = await api("/api/events");
    setEvents(listed.events ?? listed);
    if (!id) return;
    const [detail, taskResult, audit] = await Promise.all([
      api(`/api/events/${id}`),
      api(`/api/events/${id}/task`),
      api(`/api/events/${id}/timeline`),
    ]);
    setEvent(detail);
    setTask(taskResult.task);
    setTimeline(audit);
    try { setAnalysis(await api(`/api/events/${id}/analysis`)); }
    catch { setAnalysis(null); }
  }, [id]);

  useEffect(() => { refresh().catch((e: Error) => setError(e.message)); }, [refresh]);

  async function command(path: string, body: object) {
    setBusy(true); setError("");
    try { await api(path, body); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Request failed"); }
    finally { setBusy(false); }
  }

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true); setError("");
    const data = new FormData(e.currentTarget);
    try {
      const created = await api("/api/events", {
        location: data.get("location"),
        asset_type: "air_conditioner",
        description: data.get("description"),
      });
      navigate(`/events/${created.event_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  if (!id) return (
    <section className={styles.page}>
      <div className={styles.hero}>
        <div><p className={styles.kicker}>LOCAL AUDIT WORKFLOW</p><h1>{tasksOnly ? "Tasks" : "Events"}</h1>
        <p>事件、任务与审计状态均来自本机 SQLite Runtime。</p></div>
      </div>
      {!tasksOnly && <form className={styles.card} onSubmit={create}>
        <h2>异常上报</h2>
        <label>位置<input name="location" defaultValue="A08" required /></label>
        <label>异常描述<textarea name="description" placeholder="Describe the observed air-conditioner anomaly." required /></label>
        {error && <p className={styles.error}>{error}</p>}
        <button type="submit" disabled={busy}>创建 Event</button>
      </form>}
      <div className={styles.grid}>{events.map((item) => (
        <Link className={styles.card} key={item.event_id ?? item.id} to={`/events/${item.event_id ?? item.id}`}>
          <strong>{item.description ?? item.title ?? item.event_id ?? item.id}</strong>
          <span className={styles.status}>{item.status ?? item.runtime_status}</span>
        </Link>
      ))}</div>
    </section>
  );

  const status = event?.status ?? "LOADING";
  const taskId = task?.task_id;
  return (
    <section className={styles.page}>
      <div className={styles.hero}><div><p className={styles.kicker}>EVENT DETAIL</p>
        <h1>{status}</h1><p className={styles.mono}>{id}</p></div>
        <button onClick={() => refresh()} disabled={busy}>刷新</button>
      </div>
      {error && <p className={styles.error}>{error}</p>}
      <div className={styles.actions}>
        {status === "NEW" && <button disabled={busy} onClick={() => command(`/api/events/${id}/analysis`, {})}>运行 AI Analysis</button>}
        {status === "PENDING_HUMAN_REVIEW" && <>
          <button disabled={busy} onClick={() => command(`/api/events/${id}/review`, {action:"approve", comment:"Judge approved"})}>Human Review: Approve</button>
          <button disabled={busy} onClick={() => command(`/api/events/${id}/review`, {action:"reject", comment:"Judge rejected"})}>Reject</button></>}
        {status === "APPROVED" && <button disabled={busy} onClick={() => command(`/api/events/${id}/task`, {})}>Create Task</button>}
        {status === "TASK_CREATED" && taskId && <button disabled={busy} onClick={() => command(`/api/tasks/${taskId}/start`, {})}>Start Task</button>}
        {status === "IN_PROGRESS" && taskId && <button disabled={busy} onClick={() => command(`/api/tasks/${taskId}/evidence`, {description:"现场操作员确认异常已处理，运行状态恢复正常。"})}>Submit Evidence</button>}
        {status === "EVIDENCE_SUBMITTED" && taskId && <button disabled={busy} onClick={() => command(`/api/tasks/${taskId}/review/begin`, {})}>Begin Final Review</button>}
        {status === "UNDER_REVIEW" && taskId && <>
          <button disabled={busy} onClick={() => command(`/api/tasks/${taskId}/review`, {action:"approve", comment:"Evidence verified"})}>Final Review: Approve</button>
          <button disabled={busy} onClick={() => command(`/api/tasks/${taskId}/review`, {action:"needs_more_evidence", comment:"More evidence required"})}>Needs More Evidence</button></>}
      </div>
      <div className={styles.grid}>
        <article className={styles.card}><h2>Event 信息 / Current Status</h2><pre>{JSON.stringify(event, null, 2)}</pre></article>
        <article className={styles.card}><h2>AI Analysis</h2><pre>{JSON.stringify(analysis?.analysis ?? null, null, 2)}</pre></article>
        <article className={styles.card}><h2>Digital Employee / Skill</h2><pre>{JSON.stringify(analysis?.skill ?? null, null, 2)}</pre></article>
        <article className={styles.card}><h2>Knowledge Match</h2><pre>{JSON.stringify(analysis?.knowledge_sources ?? [], null, 2)}</pre></article>
        <article className={styles.card}><h2>Responsible Owner / Task</h2><pre>{JSON.stringify(task, null, 2)}</pre></article>
        <article className={styles.card}><h2>Human Review / Evidence / Final Review</h2><p>所有命令经过 Runtime 状态机；状态刷新后从 SQLite 恢复。</p></article>
      </div>
      <article className={styles.card}><h2>Timeline ({timeline.length})</h2>
        <ol className={styles.timeline}>{timeline.map((item) => <li key={item.sequence}><b>{item.sequence}. {item.action}</b><span>{item.status} · {item.timestamp}</span></li>)}</ol>
      </article>
    </section>
  );
}

export function SettingsPage() {
  return <section className={styles.page}><div className={styles.hero}><div><p className={styles.kicker}>SETTINGS</p><h1>Local Runtime</h1><p>Provider 与 Model 由统一启动配置控制。界面偏好可通过顶部 Settings 调整。</p></div></div></section>;
}
