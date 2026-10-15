"use strict";
// All repository, issue, test and model text is rendered with textContent, never as HTML.

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

function post(path, payload) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
}

function facts(rows) {
  const dl = el("dl", "facts");
  for (const [k, v] of rows) {
    if (v === undefined || v === null || v === "") continue;
    dl.appendChild(el("dt", null, k));
    dl.appendChild(el("dd", null, v));
  }
  return dl;
}

function table(headers, rows, rowClass) {
  const t = el("table");
  const head = el("tr");
  for (const h of headers) head.appendChild(el("th", null, h));
  t.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  rows.forEach((cells, i) => {
    const tr = el("tr", rowClass ? rowClass(i) : "");
    for (const c of cells) tr.appendChild(c instanceof Node ? wrapCell(c) : el("td", null, c));
    body.appendChild(tr);
  });
  t.appendChild(body);
  return t;
}

function wrapCell(node) {
  const td = el("td");
  td.appendChild(node);
  return td;
}

function badge(status) {
  const good = ["proposed", "fixed", "resolved", "CONTAINED", "available"];
  const warn = ["unverified", "unresolved", "rejected"];
  const cls = good.includes(status) ? "ok" : warn.includes(status) ? "warn" : "bad";
  return el("span", `badge ${cls}`, status);
}

function renderDiff(diff) {
  const pre = el("pre", "diff");
  for (const line of diff.split("\n")) {
    let cls = "ctx";
    if (line.startsWith("diff --git") || line.startsWith("---") || line.startsWith("+++")) cls = "hdr";
    else if (line.startsWith("@@")) cls = "hunk";
    else if (line.startsWith("+")) cls = "add";
    else if (line.startsWith("-")) cls = "del";
    pre.appendChild(el("span", cls, line + "\n"));
  }
  return pre;
}

function mockBanner(run) {
  if (run.backend === "oracle") {
    return el("p", "banner",
      "Oracle backend: replays the gold solution to check the pipeline. This is not a repair result.");
  }
  if (run.is_mock) return el("p", "banner", "Mock backend (canned responses).");
  return null;
}

// ------------------------------------------------------------------ proposal runs

function renderProposal(container, run, diff) {
  container.replaceChildren();
  const banner = mockBanner(run);
  if (banner) container.appendChild(banner);
  const status = el("p");
  status.appendChild(badge(run.status));
  container.appendChild(status);
  container.appendChild(facts([
    ["Run", run.run_id], ["Model", run.model],
    ["Context files", (run.retrieved_files || []).join(", ")],
    ["Tokens in/out", `${run.input_tokens ?? "?"} / ${run.output_tokens ?? "?"}${run.usage_is_estimate ? " (estimate)" : ""}`],
    ["Summary", run.summary],
  ]));
  for (const w of run.warnings || []) container.appendChild(el("p", "warning", w));
  for (const e of run.errors || []) container.appendChild(el("p", "error", e));
  if (diff) {
    container.appendChild(renderDiff(diff));
    container.appendChild(el("p", "muted", "Nothing was written to the repository."));
  }
}

// -------------------------------------------------------------------- repair runs

function renderRepair(container, run, patches, approval) {
  container.replaceChildren();
  const banner = mockBanner(run);
  if (banner) container.appendChild(banner);
  const status = el("p");
  status.appendChild(badge(run.status));
  status.appendChild(el("span", "muted", ` ${run.stop_reason || ""}`));
  container.appendChild(status);
  container.appendChild(facts([
    ["Run", run.run_id], ["Model", run.model], ["Sandbox", run.isolation],
    ["Baseline failing tests", (run.baseline_failing_tests || []).join(", ") || "none"],
    ["Model calls", `${run.attempts} attempt(s), ${run.extra_samples} extra sample(s)`],
    ["Tokens", run.tokens_used], ["Duration", `${run.duration_s}s`],
  ]));
  for (const w of run.warnings || []) container.appendChild(el("p", "warning", w));

  container.appendChild(el("h3", null, "Attempts"));
  container.appendChild(table(["#", "Status", "Verdict", "Tokens"],
    (run.attempt_log || []).map(a => [String(a.index), badge(a.status), a.verdict,
      `${a.input_tokens ?? "?"} / ${a.output_tokens ?? "?"}`])));

  if (run.reproduction_test) {
    container.appendChild(el("h3", null, "Reproduction test"));
    container.appendChild(el("p", null, `${run.reproduction_test.status}: ${run.reproduction_test.detail}`));
    if (run.reproduction_test.code) container.appendChild(el("pre", null, run.reproduction_test.code));
  }

  container.appendChild(el("h3", null, "Candidates (ranked)"));
  if (!(run.candidates || []).length) container.appendChild(el("p", "muted", "No valid candidate."));
  for (const card of run.candidates || []) {
    const box = el("div", "card");
    box.appendChild(el("h4", null, `#${card.rank} · candidate ${card.candidate} (${card.source})`));
    const reasons = el("ul", "reasons");
    for (const r of card.reasons) reasons.appendChild(el("li", null, r));
    for (const f of card.security) reasons.appendChild(el("li", "error", f));
    box.appendChild(reasons);
    const diff = patches ? patches[String(card.candidate)] : (card.rank === 1 ? run.diff : "");
    if (diff) box.appendChild(renderDiff(diff));
    container.appendChild(box);
  }
  if ((run.candidates || []).length) container.appendChild(approvalForm(run, approval));
}

function approvalForm(run, approval) {
  const box = el("div", "approval");
  box.appendChild(el("h3", null, "Human approval"));
  if (approval) {
    box.appendChild(el("p", null,
      `Approved: candidate ${approval.candidate} by ${approval.reviewer} at ${approval.approved_at}.`));
    box.appendChild(el("p", "muted",
      `Write it to the working tree with: coderepair apply ${approval.run_id} --repo <path> (no git, no push).`));
    return box;
  }
  const controls = el("div", "controls");
  const reviewer = el("input");
  reviewer.placeholder = "reviewer name";
  reviewer.maxLength = 80;
  const candidate = el("select");
  for (const card of run.candidates) {
    const opt = el("option", null, `candidate ${card.candidate}`);
    opt.value = String(card.candidate);
    candidate.appendChild(opt);
  }
  const ack = el("input");
  ack.type = "checkbox";
  const ackLabel = el("label", "check");
  ackLabel.appendChild(ack);
  ackLabel.appendChild(document.createTextNode(" I reviewed the risks"));
  const button = el("button", "primary", "Approve");
  button.type = "button";
  const out = el("div");
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const record = await post(`/api/runs/${encodeURIComponent(run.run_id)}/approval`, {
        reviewer: reviewer.value, candidate: Number(candidate.value), acknowledge_risks: ack.checked,
      });
      box.replaceWith(approvalForm(run, record));
    } catch (err) {
      out.replaceChildren(el("p", "error", err.message));
      button.disabled = false;
    }
  });
  controls.append(reviewer, candidate, ackLabel, button);
  box.append(el("p", "muted", "Approval records who accepted which diff. It does not write to any repository."),
    controls, out);
  return box;
}

// -------------------------------------------------------------------------- tasks

async function showTask(taskId) {
  const detail = document.getElementById("task-detail");
  const view = document.getElementById("task-template").content.cloneNode(true);
  detail.replaceChildren(view);
  const [task, ranking] = await Promise.all([
    api(`/api/tasks/${encodeURIComponent(taskId)}`),
    api(`/api/tasks/${encodeURIComponent(taskId)}/retrieval`),
  ]);
  detail.querySelector(".task-title").textContent = task.title;
  detail.querySelector(".meta").textContent =
    `${task.id} · ${task.category} · ${task.difficulty} · ${task.files.length} files · ${task.issue_style}`;
  detail.querySelector(".issue").textContent = task.issue;
  const tbody = detail.querySelector(".ranking tbody");
  for (const item of ranking.slice(0, 8)) {
    const tr = el("tr", item.is_test ? "test" : "");
    tr.appendChild(el("td", "num", item.score.toFixed(2)));
    tr.appendChild(el("td", "path", item.path));
    tr.appendChild(el("td", null, item.reasons.join("; ")));
    tbody.appendChild(tr);
  }
  const result = detail.querySelector(".result");
  const buttons = detail.querySelectorAll(".controls button");
  async function run(kind) {
    buttons.forEach(b => { b.disabled = true; });
    result.replaceChildren(el("p", "muted", kind === "repair"
      ? "Running the repair loop (model calls + sandboxed tests)…" : "Asking the model…"));
    try {
      const backend = detail.querySelector(".backend").value;
      if (kind === "repair") {
        const body = await post(`/api/tasks/${encodeURIComponent(taskId)}/repairs`, {
          backend,
          max_attempts: Number(detail.querySelector(".attempts").value),
          candidates: Number(detail.querySelector(".candidates").value),
          repro_test: detail.querySelector(".repro").checked,
        });
        renderRepair(result, body, null, null);
      } else {
        const body = await post(`/api/tasks/${encodeURIComponent(taskId)}/proposals`, { backend });
        renderProposal(result, body, body.diff);
      }
      loadRuns();
    } catch (err) {
      result.replaceChildren(el("p", "error", err.message));
    } finally {
      buttons.forEach(b => { b.disabled = false; });
    }
  }
  detail.querySelector(".repair").addEventListener("click", () => run("repair"));
  detail.querySelector(".propose").addEventListener("click", () => run("propose"));
}

// --------------------------------------------------------------------------- runs

async function showRun(runId) {
  const detail = document.getElementById("run-detail");
  const data = await api(`/api/runs/${encodeURIComponent(runId)}`);
  detail.replaceChildren(el("h2", null, `Run ${runId}`));
  const result = el("div", "result");
  detail.appendChild(result);
  if (data.summary.mode === "repair-loop") {
    renderRepair(result, { ...data.summary, diff: data.diff }, data.candidate_patches, data.approval);
  } else {
    renderProposal(result, data.summary, data.diff);
  }
  detail.appendChild(el("h3", null, `Trace (${data.trace.length} events)`));
  detail.appendChild(table(["+s", "Event", "Detail"], data.trace.map(e => [
    String(e.t), e.kind, e.label || e.verdict || e.summary || e.error || "",
  ])));
}

async function loadRuns() {
  const list = document.getElementById("run-list");
  const runs = await api("/api/runs?limit=30");
  list.replaceChildren();
  if (!runs.length) list.appendChild(el("li", "muted", "No runs yet"));
  for (const run of runs) {
    const item = el("li");
    const link = el("button", "link", `${run.task_id || "repo"} · ${run.mode === "repair-loop" ? "repair" : "propose"} · ${run.backend}`);
    link.addEventListener("click", () => { showView("runs"); showRun(run.run_id).catch(showError("run-detail")); });
    item.appendChild(link);
    item.appendChild(badge(run.status));
    list.appendChild(item);
  }
}

// ---------------------------------------------------------------------- benchmark

async function loadBenchmarks() {
  const detail = document.getElementById("bench-detail");
  const results = await api("/api/benchmarks");
  detail.replaceChildren(el("h2", null, "Comparative benchmark"));
  if (!results.length) {
    detail.appendChild(el("p", "muted", "No results yet. Run: coderepair bench --suite all --backend ollama"));
    return;
  }
  for (const result of results) {
    const meta = result.meta || {};
    const box = el("div", "card");
    box.appendChild(el("h4", null, `${result.name} · ${meta.backend} / ${meta.model}`));
    if (meta.is_mock) box.appendChild(el("p", "banner", "Mock backend: checks the harness, not a result."));
    box.appendChild(el("p", "muted",
      `${meta.date} · budget ${JSON.stringify(meta.budget)} · sandbox ${meta.sandbox}`));
    const rows = Object.entries(result.summary || {}).map(([agent, s]) => [
      agent, `${s.resolved}/${s.tasks}`, `${s.pass_at_1}/${s.tasks}`, `${s.valid_patch}/${s.tasks}`,
      String(s.regressions), String(s.mean_calls), String(s.mean_tokens), `${s.median_wall_s}s`,
      Object.entries(s.failures || {}).map(([k, v]) => `${k} ${v}`).join(", "),
    ]);
    box.appendChild(table(["Agent", "Resolved", "pass@1", "Valid patch", "Regressions",
      "Calls", "Tokens", "Median wall", "Failures"], rows));
    const more = el("button", "link", "Per-task results");
    more.addEventListener("click", async () => {
      const data = await api(`/api/benchmarks/${encodeURIComponent(result.name)}`);
      const agents = Object.keys(data.summary || {});
      const tasks = [...new Set(data.rows.map(r => r.task_id))].sort();
      more.replaceWith(table(["Task", ...agents], tasks.map(t => [t, ...agents.map(a => {
        const row = data.rows.find(r => r.task_id === t && r.agent === a);
        return row ? badge(row.resolved ? "resolved" : (row.failure || row.status)) : "-";
      })])));
    });
    box.appendChild(more);
    detail.appendChild(box);
  }
}

// ------------------------------------------------------------------------ sandbox

async function loadSandbox() {
  const detail = document.getElementById("sandbox-detail");
  const info = await api("/api/sandbox");
  detail.replaceChildren(el("h2", null, "Sandbox"));
  detail.appendChild(facts([["Configured", info.configured], ["In use", info.selected]]));
  detail.appendChild(table(["Backend", "Status", "Detail", "Isolation"], info.backends.map(b => [
    b.name, badge(b.available ? "available" : "unavailable"), b.detail, b.isolation,
  ])));
  const button = el("button", "primary", "Run abuse self-test");
  button.type = "button";
  const out = el("div");
  button.addEventListener("click", async () => {
    button.disabled = true;
    out.replaceChildren(el("p", "muted", "Running hostile probes in the sandbox (about 20 s)…"));
    try {
      const report = await post("/api/sandbox/selftest");
      out.replaceChildren(el("p", null, `${report.contained}/${report.total} probes contained (${report.sandbox})`),
        table(["Probe", "Result", "Observed", "Threat"], report.probes.map(p => [
          p.name, badge(p.contained ? "CONTAINED" : "ESCAPED"), p.observed, p.threat,
        ])));
    } catch (err) {
      out.replaceChildren(el("p", "error", err.message));
    } finally {
      button.disabled = false;
    }
  });
  const controls = el("div", "controls");
  controls.appendChild(button);
  detail.append(el("h3", null, "Containment"), controls, out);
}

// ------------------------------------------------------------------------- shell

function showError(target) {
  return err => document.getElementById(target).replaceChildren(el("p", "error", err.message));
}

const loaders = { benchmark: loadBenchmarks, sandbox: loadSandbox };

function showView(name) {
  for (const tab of document.querySelectorAll(".tab")) tab.classList.toggle("active", tab.dataset.view === name);
  for (const view of document.querySelectorAll(".view")) view.hidden = view.id !== `view-${name}`;
  if (loaders[name]) loaders[name]().catch(showError(name === "benchmark" ? "bench-detail" : "sandbox-detail"));
}

async function init() {
  for (const tab of document.querySelectorAll(".tab")) tab.addEventListener("click", () => showView(tab.dataset.view));
  const tasks = await api("/api/tasks");
  for (const task of tasks) {
    const list = document.getElementById(task.id.startsWith("q") ? "task-list-public" : "task-list-fixtures");
    const item = el("li");
    const link = el("button", "link", task.id);
    link.title = task.title;
    link.addEventListener("click", () => showTask(task.id).catch(showError("task-detail")));
    item.appendChild(link);
    list.appendChild(item);
  }
  await loadRuns();
}

init().catch(showError("task-detail"));
