import "./style.css";
import { cancelRun, followRun, getCall, listRuns, startRun } from "./api/agent";
import { createWorkspace, followBoard, getBoard, listWorkspaces, pin, type BoardEvent } from "./api/board";
import { HttpError, loadSettings, saveSettings } from "./api/http";
import { VisRenderer } from "./render/vis";
import type { BoardRenderer } from "./render/types";
import { toView } from "./render/viewModel";
import { applyOps, type BoardState } from "./state/board";
import { decide, toggleMention } from "./state/input";
import { newJournal, reduce, type RunJournal } from "./state/journal";
import { $, esc, toast } from "./ui/dom";
import { renderJournal } from "./ui/journal";
import { renderNotes } from "./ui/notes";

const settings = loadSettings();
const renderer: BoardRenderer = new VisRenderer(); // swap the board engine here
renderer.mount($("net"));

let ws: string | null = null;
let board: BoardState | null = null;
let title = "";
let mentions: string[] = [];
let journals: RunJournal[] = [];
let activeRun: string | null = null;
let boardAbort: AbortController | null = null;
let runsAbort: AbortController | null = null;
let refetchTimer: ReturnType<typeof setTimeout> | undefined;

const showErr = (e: unknown) => toast(e instanceof Error ? e.message : String(e), true);
const labelOf = (k: string) => board?.objects.find((o) => o.key === k)?.label ?? k;

// ── board ────────────────────────────────────────────────────────────
function draw(): void {
  if (!board) return;
  const latest = journals[journals.length - 1]?.runId;
  renderer.render(toView(board, mentions, latest));
  const shown = board.objects.filter((o) => !o.hidden).length;
  $("wsPill").innerHTML = `<b>${esc(title)}</b> · объектов ${shown}`;
  renderNotes($("notes"), board, (k) => renderer.focus(k));
}

async function refetch(): Promise<void> {
  if (!ws) return;
  const r = await getBoard(settings, ws);
  board = r.state;
  title = r.workspace.title;
  draw();
}

function scheduleRefetch(): void {
  clearTimeout(refetchTimer);
  refetchTimer = setTimeout(() => refetch().catch(showErr), 150);
}

function onBoardEvent(e: BoardEvent): void {
  if (e.type === "ops" && board) {
    const next = applyOps(board, e.ops);
    if (next) {
      board = next;
      draw();
      return;
    }
  }
  scheduleRefetch(); // ready, resync, or ops that need the server's fold
}

// ── runs / journal ───────────────────────────────────────────────────
function drawJournal(): void {
  renderJournal($("journal"), journals, async (runId, callId) => {
    try {
      const c = await getCall(settings, runId, callId);
      $("dTitle").textContent = `${c.server}.${c.tool} · ${callId}`;
      $("dBody").textContent = JSON.stringify({ args: c.args, result: c.payload }, null, 2);
      $("detail").hidden = false;
    } catch (e) {
      showErr(e);
    }
  });
}

function setRunning(runId: string | null): void {
  activeRun = runId;
  $("box").classList.toggle("running", !!runId);
  $<HTMLInputElement>("q").placeholder = runId ? "идёт запрос… «стоп» — остановить" : "встречи Путина в Китае";
  $("st").textContent = runId ? "агент работает…" : "готово";
}

function follow(runId: string, text: string, runMentions: string[], live: boolean, token?: string): void {
  journals.push(newJournal(runId, text, runMentions));
  journals = journals.slice(-5);
  if (live) setRunning(runId);
  drawJournal();
  followRun(settings, runId, (ev) => {
    const i = journals.findIndex((j) => j.runId === runId);
    if (i < 0) return;
    journals[i] = reduce(journals[i], ev);
    drawJournal();
    if (ev.type === "done" && activeRun === runId) {
      setRunning(null);
      $("st").textContent = { done: "готово", failed: "ошибка", cancelled: "остановлено" }[ev.status as string] ?? "";
      draw();
    }
  }, runsAbort!.signal, token).catch(showErr);
}

// ── workspace ────────────────────────────────────────────────────────
async function openWorkspace(id: string): Promise<void> {
  boardAbort?.abort();
  runsAbort?.abort();
  ws = id || null;
  board = null;
  mentions = [];
  journals = [];
  setRunning(null);
  drawChips();
  drawJournal();
  renderer.render({ nodes: [], edges: [] });
  $("notes").innerHTML = "";
  if (!ws) {
    $("wsPill").textContent = "нет расследования";
    return;
  }
  boardAbort = new AbortController();
  runsAbort = new AbortController();
  followBoard(settings, ws, onBoardEvent, boardAbort.signal).catch(showErr);
  const { active, runs } = await listRuns(settings, ws, 5);
  for (const r of runs.filter((r) => r.id !== active?.id).reverse()) follow(r.id, r.text, r.mentions, false);
  if (active) follow(active.id, active.text, active.mentions, true);
}

async function loadWorkspaces(select?: string): Promise<void> {
  const list = await listWorkspaces(settings);
  $("wsSel").innerHTML = `<option value="">— расследование —</option>` +
    list.map((w) => `<option value="${esc(w.id)}">${esc(w.title)}</option>`).join("");
  if (select) $<HTMLSelectElement>("wsSel").value = select;
}

// ── input ────────────────────────────────────────────────────────────
function drawChips(): void {
  document.querySelectorAll("#box .chip").forEach((e) => e.remove());
  for (const k of mentions) {
    const c = document.createElement("span");
    c.className = "chip";
    c.textContent = "@" + labelOf(k);
    c.title = `${k} (клик — убрать)`;
    c.onclick = () => { mentions = toggleMention(mentions, k); drawChips(); draw(); };
    $("box").insertBefore(c, $("q"));
  }
}

async function submit(text: string): Promise<void> {
  const d = decide(text, !!activeRun);
  if (d === "ignore") return;
  if (d === "busy") return toast("Идёт запрос. «стоп» — остановить его.");
  if (d === "stop") {
    await cancelRun(settings, activeRun!);
    $<HTMLInputElement>("q").value = "";
    return;
  }
  if (!ws) return toast("Сначала создай или выбери расследование (＋ сверху).");
  try {
    const r = await startRun(settings, ws, text, mentions);
    const sent = mentions;
    $<HTMLInputElement>("q").value = "";
    mentions = [];
    drawChips();
    follow(r.run_id, text, sent, true, r.stream_token);
  } catch (e) {
    if (e instanceof HttpError && e.status === 409) {
      toast("В этом расследовании уже идёт запрос.");
      const { active } = await listRuns(settings, ws, 1);
      if (active && !journals.some((j) => j.runId === active.id)) {
        follow(active.id, active.text, active.mentions, true);
      }
    } else showErr(e);
  }
}

$<HTMLInputElement>("q").addEventListener("keydown", (e) => {
  const q = e.target as HTMLInputElement;
  if (e.key === "Backspace" && !q.value && mentions.length) {
    mentions = mentions.slice(0, -1);
    drawChips();
    draw();
    return;
  }
  if (e.key === "Enter") submit(q.value.trim()).catch(showErr);
});

renderer.on("select", (k) => { mentions = toggleMention(mentions, k); drawChips(); draw(); $("q").focus(); });
renderer.on("dragEnd", (k, pos) => { if (ws && pos) pin(settings, ws, k, pos.x, pos.y).catch(showErr); });
renderer.on("open", (k) => {
  const o = board?.objects.find((x) => x.key === k);
  if (o) toast(`${o.label} · ${o.type}${o.description ? ` — ${o.description}` : ""}`);
});

// ── chrome ───────────────────────────────────────────────────────────
async function health(): Promise<void> {
  const probe = async (path: string) => (await fetch(path).then((r) => r.ok).catch(() => false));
  const [b, a] = await Promise.all([probe("/board/health"), probe("/agent/health")]);
  $("srv").innerHTML = `доска <span class="${b ? "up" : "down"}">●</span> · агент <span class="${a ? "up" : "down"}">●</span>`;
}

$<HTMLSelectElement>("wsSel").onchange = (e) => openWorkspace((e.target as HTMLSelectElement).value).catch(showErr);
$("newWs").onclick = async () => {
  const t = prompt("Название расследования", "Новое расследование");
  if (!t) return;
  try {
    const w = await createWorkspace(settings, t);
    await loadWorkspaces(w.id);
    await openWorkspace(w.id);
  } catch (e) {
    showErr(e);
  }
};
$("cfgBtn").onclick = () => { $<HTMLInputElement>("cKey").value = settings.key; $("cfg").hidden = false; };
$("cSave").onclick = () => {
  settings.key = $<HTMLInputElement>("cKey").value.trim();
  saveSettings(settings);
  $("cfg").hidden = true;
  boot().catch(showErr);
};
$("dClose").onclick = () => { $("detail").hidden = true; };

async function boot(): Promise<void> {
  await health();
  if (!settings.key) {
    $("cfg").hidden = false;
    return;
  }
  await loadWorkspaces();
}

boot().catch(showErr);
setInterval(() => health().catch(() => {}), 15000);
