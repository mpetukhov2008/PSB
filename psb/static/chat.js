"use strict";
const $ = id => document.getElementById(id);
let history = [], generation = 0, busy = false, activeRequest = null;
const selected = new Set();
const labels = {answered: "Ответ с основаниями", corrected: "Предпосылка исправлена", partial: "Частичный ответ", insufficient: "Недостаточно данных", clarification: "Нужно уточнение", out_of_scope: "Вне области работы", refused: "Запрос отклонён", excerpts: "Найденные выдержки", verification_failed: "Проверка не пройдена"};
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function showError(text) { $("error").textContent = text; $("error").hidden = !text; }
async function getJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Сервис временно недоступен");
  return data;
}
async function openSource(id, quote) {
  const ownGeneration = generation;
  try {
    const doc = await getJson("/api/documents/" + encodeURIComponent(id));
    if (ownGeneration !== generation) return;
    $("source-title").textContent = doc.title;
    const body = $("source-body"); body.replaceChildren();
    body.append(el("p", `${doc.revision} · с ${doc.effective_from || "дата не указана"}${doc.effective_to ? " до " + doc.effective_to + " (не включая)" : ""}`));
    if (quote) body.append(el("blockquote", quote));
    for (const section of doc.sections) body.append(el("h3", section.locator), el("p", section.text));
    if (!$("source-dialog").open) $("source-dialog").showModal();
  } catch (error) { if (ownGeneration === generation) showError(error.message); }
}
function bubble(role, text) {
  const node = el("article", undefined, "message " + role);
  node.append(el("span", role === "user" ? "ВЫ" : "ОПОРА · ПО БАЗЕ ДОКУМЕНТОВ", "message-label"));
  if (text) node.append(el("p", text));
  $("conversation").append(node);
  return node;
}
function renderAnswer(result) {
  const node = bubble("assistant");
  node.append(el("div", labels[result.status] || "Результат", "badge"));
  node.append(el("p", result.date_precision === "month" ? `Редакции за ${result.event_date.slice(0, 7)} · месяц события` : `Редакции на ${result.event_date}${result.explicit_date ? " · дата события" : " · текущая дата"}`, "muted"));
  if (result.message) node.append(el("p", result.message));
  const byId = new Map(result.sources.map(f => [f.id, f]));
  for (const claim of result.claims) {
    const box = el("div", undefined, "claim"); box.append(el("p", claim.text));
    for (const evidence of claim.evidence) {
      const source = byId.get(evidence.fragment_id);
      if (!source) continue;
      const link = el("button", source.title + " · " + source.locator + " ↗", "citation");
      link.type = "button"; link.addEventListener("click", () => openSource(source.document_id, evidence.quote)); box.append(link);
    }
    node.append(box);
  }
  if (result.missing.length) {
    node.append(el("h3", "Чего не хватает"));
    const list = el("ul"); result.missing.forEach(text => list.append(el("li", text))); node.append(list);
  }
  if (result.sources.length) {
    const sources = el("details", undefined, "sources"); sources.open = result.status === "excerpts";
    sources.append(el("summary", "Найденные положения · " + result.sources.length));
    for (const source of result.sources) {
      const link = el("button", undefined, "source"); link.type = "button";
      link.append(el("strong", source.title + " · " + source.locator), el("small", source.revision), el("p", source.text));
      link.addEventListener("click", () => openSource(source.document_id, source.text)); sources.append(link);
    }
    node.append(sources);
  }
  const trace = el("details"); trace.append(el("summary", "Как получен результат"));
  const steps = el("ol"); result.stages.forEach(step => steps.append(el("li", `${step.name} · ${step.elapsed_ms} мс`))); trace.append(steps);
  for (const note of result.retrieval_notes || []) trace.append(el("p", note, "muted"));
  trace.append(el("p", result.mode === "model" ? "Для генерации и отдельной смысловой проверки используется одна модель. Это не гарантия юридической правильности." : "Локальный поиск по словам. Юридические выводы не формировались."));
  node.append(trace);
  const download = el("button", "Скачать результат · JSON", "download-result");
  download.type = "button";
  download.addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], {type: "application/json"}));
    const link = el("a"); link.href = url; link.download = "psb-result.json";
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  node.append(download);
  node.scrollIntoView({block: "start", behavior: "auto"});
}
$("chat-form").addEventListener("submit", async event => {
  event.preventDefault(); if (busy) return;
  const question = $("question").value.trim(); if (question.length < 2) return;
  const ownGeneration = generation;
  busy = true; $("send").disabled = true; $("activity").hidden = false; showError("");
  $("intro").hidden = true; const questionBubble = bubble("user", question); $("question").value = "";
  activeRequest = new AbortController();
  try {
    const payload = {question, history: history.slice(-8).map(turn => ({role: turn.role, content: turn.content.slice(0, 2800)})), document_ids: [...selected], event_date: $("event-date").value};
    while (new TextEncoder().encode(JSON.stringify(payload)).length > 90000 && payload.history.length) payload.history.splice(0, 2);
    const result = await getJson("/api/chat", {method: "POST", signal: activeRequest.signal, headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
    if (ownGeneration !== generation) return;
    renderAnswer(result);
    history.push({role: "user", content: question}, {role: "assistant", content: [result.message, ...result.claims.map(c => c.text)].join("\n")});
    history = history.slice(-8);
  } catch (error) {
    if (ownGeneration === generation) {
      showError(error.name === "AbortError" ? "Ожидание остановлено. Обработка на сервере может завершиться отдельно." : error.message);
      $("question").value = question;
      questionBubble.append(el("small", "Ответ не получен", "muted"));
    }
  } finally {
    if (ownGeneration === generation) { busy = false; activeRequest = null; $("send").disabled = false; $("activity").hidden = true; $("question").focus({preventScroll: true}); }
  }
});
$("new-chat").addEventListener("click", () => {
  generation++; if (activeRequest) activeRequest.abort(); activeRequest = null;
  history = []; busy = false; $("conversation").replaceChildren(); $("intro").hidden = false;
  if ($("source-dialog").open) $("source-dialog").close();
  $("question").value = ""; $("event-date").value = ""; $("activity").hidden = true; $("send").disabled = false; showError("");
});
$("cancel-wait").addEventListener("click", () => { if (activeRequest) activeRequest.abort(); });
$("close-source").addEventListener("click", () => $("source-dialog").close());
document.querySelectorAll("[data-question]").forEach(button => button.addEventListener("click", () => { $("question").value = button.dataset.question; $("question").focus(); }));
let theme = "dark";
try { theme = localStorage.getItem("psb-theme") === "light" ? "light" : "dark"; } catch (_) { /* Optional preference storage. */ }
function applyTheme() { document.documentElement.dataset.theme = theme; $("theme").textContent = theme === "dark" ? "Светлая тема" : "Тёмная тема"; }
applyTheme();
$("theme").addEventListener("click", () => { theme = theme === "dark" ? "light" : "dark"; applyTheme(); try { localStorage.setItem("psb-theme", theme); } catch (_) {} });
$("doc-filter").addEventListener("input", () => document.querySelectorAll(".document").forEach(node => { node.hidden = !node.textContent.toLowerCase().includes($("doc-filter").value.toLowerCase()); }));
async function initialize() {
  try {
    const [data, health] = await Promise.all([getJson("/api/documents"), getJson("/api/health")]);
    $("doc-count").textContent = "· " + data.documents.length;
    $("corpus-banner").textContent = (data.corpus_kind === "demo" ? "УЧЕБНЫЙ РЕЖИМ · Вымышленные регламенты для проверки. Это не документы банка." : "База предоставленных документов · Ответы ограничены её содержимым.") + (health.model_ready ? " Модель подключена к API; доступ проверяется при запросе." : " Модель не подключена — доступны выдержки.");
    if (data.corpus_kind === "provided") {
      const examples = [
        ["Какая арендная плата по договору с Северным Складом?", "Арендная плата и основания"],
        ["Нужно ли было одобрение директора для договора на 12 млн в августе 2024 года?", "Редакция регламента на дату"],
        ["Какой гарантийный срок по договору с Альфа-Трейдинг?", "Гарантия по нужному договору"]
      ];
      document.querySelectorAll("[data-question]").forEach((button, index) => {
        if (examples[index]) {
          button.dataset.question = examples[index][0];
          button.replaceChildren(document.createTextNode(examples[index][1] + " "), el("span", "↗"));
        }
      });
    }
    for (const doc of data.documents) {
      const card = el("div", undefined, "document"); const label = el("label");
      const checkbox = el("input"); checkbox.type = "checkbox"; checkbox.value = doc.id;
      checkbox.addEventListener("change", () => checkbox.checked ? selected.add(doc.id) : selected.delete(doc.id));
      label.append(checkbox, el("span", doc.title)); card.append(label, el("small", doc.revision + " · с " + (doc.effective_from || "не указано")));
      const open = el("button", "Читать документ ↗"); open.type = "button"; open.addEventListener("click", () => openSource(doc.id)); card.append(open); $("documents").append(card);
    }
  } catch (error) { $("corpus-banner").textContent = "Не удалось загрузить базу документов"; showError(error.message); }
}
initialize();

