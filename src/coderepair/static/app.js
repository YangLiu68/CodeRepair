"use strict";
// All repository, issue and model text is rendered with textContent, never innerHTML.

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

function renderRun(container, run, diff) {
  container.replaceChildren();
  if (run.backend === "oracle") {
    container.appendChild(el("p", "banner",
      "Oracle backend: replays the gold solution to check the pipeline. This is not a repair result."));
  } else if (run.is_mock) {
    container.appendChild(el("p", "banner", "Mock backend (canned responses)."));
  }
  const facts = el("dl", "facts");
  const rows = [
    ["Status", run.status], ["Run", run.run_id], ["Model", run.model],
    ["Context files", (run.retrieved_files || []).join(", ")],
    ["Tokens in/out", `${run.input_tokens ?? "?"} / ${run.output_tokens ?? "?"}${run.usage_is_estimate ? " (estimate)" : ""}`],
  ];
  if (run.summary) rows.push(["Summary", run.summary]);
  for (const [k, v] of rows) { facts.appendChild(el("dt", null, k)); facts.appendChild(el("dd", null, v)); }
  container.appendChild(facts);
  for (const w of run.warnings || []) container.appendChild(el("p", "warning", w));
  for (const e of run.errors || []) container.appendChild(el("p", "error", e));
  if (diff) {
    container.appendChild(renderDiff(diff));
    container.appendChild(el("p", "muted", "Nothing was written to the repository. Review the diff above."));
  }
}

async function showTask(taskId) {
  const detail = document.getElementById("detail");
  const view = document.getElementById("detail-template").content.cloneNode(true);
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
  const button = detail.querySelector(".propose");
  const result = detail.querySelector(".result");
  button.addEventListener("click", async () => {
    button.disabled = true;
    result.replaceChildren(el("p", "muted", "Running…"));
    try {
      const backend = detail.querySelector(".backend").value;
      const run = await api(`/api/tasks/${encodeURIComponent(taskId)}/proposals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ backend }),
      });
      renderRun(result, run, run.diff);
      loadRuns();
    } catch (err) {
      result.replaceChildren(el("p", "error", err.message));
    } finally {
      button.disabled = false;
    }
  });
}

async function showRun(runId) {
  const detail = document.getElementById("detail");
  const data = await api(`/api/runs/${encodeURIComponent(runId)}`);
  detail.replaceChildren(el("h2", null, `Run ${runId}`));
  const result = el("div", "result");
  detail.appendChild(result);
  renderRun(result, data.summary, data.diff);
  detail.appendChild(el("h3", null, `Trace (${data.trace.length} events)`));
  const list = el("ol", "trace");
  for (const event of data.trace) {
    const item = el("li");
    item.appendChild(el("strong", null, `${event.kind} `));
    item.appendChild(el("span", "muted", `+${event.t}s`));
    list.appendChild(item);
  }
  detail.appendChild(list);
}

async function loadRuns() {
  const list = document.getElementById("run-list");
  const runs = await api("/api/runs?limit=15");
  list.replaceChildren();
  if (!runs.length) list.appendChild(el("li", "muted", "No runs yet"));
  for (const run of runs) {
    const item = el("li");
    const link = el("button", "link", `${run.task_id || "repo"} · ${run.backend} · ${run.status}`);
    link.addEventListener("click", () => showRun(run.run_id).catch(showError));
    item.appendChild(link);
    list.appendChild(item);
  }
}

function showError(err) {
  document.getElementById("detail").replaceChildren(el("p", "error", err.message));
}

async function init() {
  const tasks = await api("/api/tasks");
  const list = document.getElementById("task-list");
  for (const task of tasks) {
    const item = el("li");
    const link = el("button", "link", task.id);
    link.title = task.title;
    link.addEventListener("click", () => showTask(task.id).catch(showError));
    item.appendChild(link);
    list.appendChild(item);
  }
  await loadRuns();
}

init().catch(showError);
