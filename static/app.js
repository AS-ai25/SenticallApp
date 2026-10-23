/* Senticall frontend */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------------------------------------------------------------- state
  const state = {
    callId: null,
    transcript: [],
    analysis: null,
    selected: [],
    mode: "text",
    speaker: "customer",
    busy: false,
    recorder: null,
    chunks: [],
    uploadBlob: null,
    history: [],
    dash: null,
    charts: {},
    insights: null,
    customerValid: false,
    enrichment: null,
  };

  // ---------------------------------------------------------------- helpers
  function toast(msg, err = false) {
    const el = document.createElement("div");
    el.className = "toast" + (err ? " err" : "");
    el.textContent = msg;
    $("toast-root").appendChild(el);
    setTimeout(() => el.remove(), err ? 6000 : 3200);
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, opts);
    let body = null;
    try { body = await res.json(); } catch (_) { /* no json */ }
    if (!res.ok) {
      let msg = body?.detail || res.statusText;
      if (Array.isArray(msg)) msg = msg.map((e) => `${e.loc?.slice(-1)[0]}: ${e.msg}`).join("; ");
      throw new Error(msg);
    }
    return body;
  }

  function setProgress(text) {
    const p = $("progress");
    if (!text) { p.classList.add("hidden"); return; }
    p.classList.remove("hidden");
    $("progress-text").textContent = text;
  }

  function setBusy(b) {
    state.busy = b;
    $("btn-analyze").disabled = b || !state.customerValid;
    $("btn-rec").disabled = b;
    $("btn-sample").disabled = b;
  }

  // ---------------------------------------------------------------- usage / cost
  const fmtTok = (n) => n >= 1e6 ? (n / 1e6).toFixed(2) + "M" : n >= 1000 ? (n / 1000).toFixed(1) + "K" : String(n);
  const fmtUsd = (v) => v == null ? "n/a" : v < 0.01 ? "$" + v.toFixed(5) : v < 1 ? "$" + v.toFixed(4) : "$" + v.toFixed(2);
  const usageLine = (u) => u ? `${fmtTok(u.total_tokens)} tok · ${fmtUsd(u.cost_usd)} · ${u.seconds}s` : "";

  async function loadUsage() {
    try {
      const u = await api("/api/usage?last=1");
      state.usage = u;
      const chip = $("chip-usage");
      chip.querySelector("span:last-child").innerHTML = `session <b>${fmtUsd(u.session.cost_usd)}</b> · ${fmtTok(u.session.total_tokens)} tok`;
      chip.title = `All time: ${fmtUsd(u.all_time.cost_usd)} over ${u.all_time.calls} Claude calls — click for details`;
    } catch (_) { /* ignore */ }
  }

  function usageStat(label, t, sub) {
    return `<div class="ustat"><div class="l">${label}</div><div class="v">${fmtUsd(t.cost_usd)}<small>${t.calls} calls</small></div>
      <div class="sub">${fmtTok(t.total_tokens)} tokens · in ${fmtTok(t.input_tokens)} · out ${fmtTok(t.output_tokens)} · cache read ${fmtTok(t.cache_read_tokens)} · cache write ${fmtTok(t.cache_write_tokens)}${t.unpriced_calls ? ` · ${t.unpriced_calls} unpriced` : ""}${sub ? "<br>" + sub : ""}</div></div>`;
  }

  async function openUsageDrawer() {
    let u;
    try { u = await api("/api/usage?last=30"); } catch (e) { toast(e.message, true); return; }
    state.usage = u;
    const p = u.current_price;
    const priceLine = p
      ? `<div class="price-line">Current model <b>${esc(u.current_model)}</b> — per 1M tokens: input <b>$${p.input}</b> · output <b>$${p.output}</b> · cache read <b>$${p.cache_read}</b> · cache write <b>$${p.cache_write}</b></div>`
      : `<div class="price-line">Current model <b>${esc(u.current_model)}</b> — no price on file, costs shown as n/a.</div>`;
    const rows = (arr, key) => arr.map((r) => `<tr><td>${esc(r[key])}</td><td class="num">${r.calls}</td><td class="num">${fmtTok(r.input_tokens)}</td><td class="num">${fmtTok(r.output_tokens)}</td><td class="num">${fmtTok(r.cache_read_tokens)}</td><td class="num">${fmtUsd(r.cost_usd)}</td></tr>`).join("");
    const recent = u.recent.map((r) => `<tr><td class="mono">${esc(r.ts.replace("T", " "))}</td><td>${esc(r.kind.replace("_", " "))}</td><td>${esc(r.model)}</td><td class="num">${fmtTok(r.input_tokens + r.cache_read_tokens + r.cache_write_tokens)}</td><td class="num">${fmtTok(r.output_tokens)}</td><td class="num">${r.seconds}s</td><td class="num">${fmtUsd(r.cost_usd)}</td></tr>`).join("");
    const none = (n) => `<tr><td colspan="${n}" class="tiny">no calls yet</td></tr>`;
    const root = $("drawer-root");
    root.innerHTML = `
      <div class="drawer-root">
        <div class="drawer-back" id="drawer-back"></div>
        <div class="drawer" style="width:640px">
          <div class="panel-head"><h2>Token usage &amp; cost</h2><span class="spacer"></span><span class="tiny">server up since ${esc(u.server_started.replace("T", " "))}</span><button class="btn small ghost" id="drawer-close">✕</button></div>
          <div class="drawer-body">
            <div class="ustats">
              ${usageStat("This session", u.session, "since the server started")}
              ${usageStat("All time", u.all_time, "every Claude call logged in data/usage.jsonl")}
            </div>
            ${priceLine}
            <div class="block"><h4>By model</h4><div class="table-wrap"><table class="utable"><thead><tr><th>Model</th><th class="num">Calls</th><th class="num">Input</th><th class="num">Output</th><th class="num">Cache read</th><th class="num">Cost</th></tr></thead><tbody>${rows(u.by_model, "model") || none(6)}</tbody></table></div></div>
            <div class="block"><h4>By type</h4><div class="table-wrap"><table class="utable"><thead><tr><th>Type</th><th class="num">Calls</th><th class="num">Input</th><th class="num">Output</th><th class="num">Cache read</th><th class="num">Cost</th></tr></thead><tbody>${rows(u.by_kind, "kind") || none(6)}</tbody></table></div></div>
            <div class="block"><h4>Recent calls</h4><div class="table-wrap"><table class="utable"><thead><tr><th>Time</th><th>Type</th><th>Model</th><th class="num">In</th><th class="num">Out</th><th class="num">Latency</th><th class="num">Cost</th></tr></thead><tbody>${recent || none(7)}</tbody></table></div></div>
            <div class="tiny">Costs are computed locally from the token counts returned by the API and the Anthropic price list in app/usage.py (USD per million tokens). Whisper runs locally and costs nothing. "In" includes cached tokens.</div>
            <div class="btn-row"><button class="btn small danger" id="usage-reset">Reset usage log</button></div>
          </div>
        </div>
      </div>`;
    const close = () => { root.innerHTML = ""; };
    $("drawer-back").addEventListener("click", close);
    $("drawer-close").addEventListener("click", close);
    $("usage-reset").addEventListener("click", async () => {
      if (!confirm("Delete the whole usage log (data/usage.jsonl)?")) return;
      try { await api("/api/usage", { method: "DELETE" }); toast("Usage log cleared."); close(); loadUsage(); } catch (e) { toast(e.message, true); }
    });
    document.addEventListener("keydown", function onKey(e) { if (e.key === "Escape") { close(); document.removeEventListener("keydown", onKey); } });
  }
  $("chip-usage").addEventListener("click", openUsageDrawer);

  // ---------------------------------------------------------------- health
  async function loadHealth() {
    try {
      const h = await api("/api/health");
      const m = $("chip-model"); m.className = "chip " + (h.api_key ? "ok" : "bad");
      m.querySelector("span:last-child").textContent = h.api_key ? h.model : "no API key";
      const s = $("chip-stt"); s.className = "chip ok";
      s.querySelector("span:last-child").textContent = `whisper ${h.whisper_model}` + (h.whisper_device !== "not loaded" ? ` · ${h.whisper_device}` : "");
      const c = $("chip-calls"); c.className = "chip ok";
      c.querySelector("span:last-child").textContent = `${h.calls} calls (${h.live_calls} live)`;
      if (!h.api_key) toast("ANTHROPIC_API_KEY is missing on the server — analysis is disabled.", true);
    } catch (e) { toast("Server unreachable: " + e.message, true); }
  }

  // ---------------------------------------------------------------- customer form
  const FIELDS = { phone: "f-phone", full_name: "f-name", email: "f-email", product: "f-product", agent_name: "f-agent" };
  const LABELS = { phone: "phone", full_name: "full name", email: "email", product: "product", agent_name: "agent" };

  function readCustomer() {
    const c = {};
    for (const [k, id] of Object.entries(FIELDS)) c[k] = $(id).value.trim();
    if (state.enrichment) {
      for (const k of ["gender", "age", "state", "region", "income_group", "education"]) {
        if (state.enrichment[k] != null) c[k] = state.enrichment[k];
      }
    }
    return c;
  }

  function validateLocal(c) {
    const errors = {};
    if (!/^\d{7,12}$/.test(c.phone)) errors.phone = c.phone ? "7-12 digits" : "required";
    if (c.full_name.length < 2) errors.full_name = c.full_name ? "too short" : "required";
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(c.email)) errors.email = c.email ? "invalid email" : "required";
    if (c.product.length < 2) errors.product = c.product ? "too short" : "required";
    if (c.agent_name.length < 2) errors.agent_name = c.agent_name ? "too short" : "required";
    return errors;
  }

  function refreshLock() {
    const c = readCustomer();
    const errors = validateLocal(c);
    const missing = Object.keys(errors);
    for (const [k, id] of Object.entries(FIELDS)) {
      const input = $(id);
      const e = $("e-" + k);
      const touched = input.dataset.touched === "1";
      input.classList.toggle("invalid", touched && !!errors[k]);
      input.classList.toggle("valid", !errors[k] && c[k] !== "");
      e.textContent = touched && errors[k] ? errors[k] : "";
    }
    const ok = missing.length === 0;
    state.customerValid = ok;
    $("col-call").classList.toggle("locked", !ok);
    $("lock-overlay").classList.toggle("hidden", ok);
    $("lock-missing").innerHTML = missing.map((k) => `<li>${esc(LABELS[k])}</li>`).join("");
    const ls = $("lockstate");
    ls.classList.toggle("ok", ok);
    ls.querySelector("span").textContent = ok ? "Customer identified — call panel unlocked" : `Call panel locked — missing: ${missing.map((k) => LABELS[k]).join(", ")}`;
    $("btn-analyze").disabled = state.busy || !ok;
  }

  async function lookupPhone() {
    const phone = $("f-phone").value.trim();
    if (!/^\d{7,12}$/.test(phone)) { $("f-phone").dataset.touched = "1"; refreshLock(); return; }
    try {
      const r = await api(`/api/customers/lookup?phone=${encodeURIComponent(phone)}`);
      if (r.found) {
        state.enrichment = r.customer;
        if (r.customer.product && !$("f-product").value.trim()) $("f-product").value = r.customer.product;
        const parts = [["Gender", r.customer.gender], ["Age", r.customer.age], ["State", r.customer.state], ["Region", r.customer.region], ["Income", r.customer.income_group], ["Education", r.customer.education]]
          .filter(([, v]) => v != null && v !== "");
        $("enrich").innerHTML = parts.map(([k, v]) => `<div><span>${k}</span>${esc(v)}</div>`).join("");
        $("enrich").classList.remove("hidden");
        toast("Customer record found — profile attached.");
      } else {
        state.enrichment = null;
        $("enrich").classList.add("hidden");
        toast("No record for this phone — fill in the details manually.");
      }
    } catch (e) { toast(e.message, true); }
    refreshLock();
  }

  for (const id of Object.values(FIELDS)) {
    const el = $(id);
    el.addEventListener("input", () => { el.dataset.touched = "1"; refreshLock(); });
    el.addEventListener("blur", () => { el.dataset.touched = "1"; refreshLock(); });
  }
  $("f-phone").addEventListener("change", lookupPhone);
  $("btn-lookup").addEventListener("click", lookupPhone);

  // ---------------------------------------------------------------- call lifecycle
  function resetCall(clearCustomer) {
    state.callId = null; state.transcript = []; state.analysis = null; state.selected = []; state.uploadBlob = null;
    $("transcript").innerHTML = '<div class="empty">The English transcript will appear here, customer on the left and agent on the right. Record, upload a call file, or type what was said.</div>';
    $("analysis").innerHTML = '<div class="empty-analysis">Analysis appears here after the first pass: exact problem, priority, urgent action, and solutions you can offer.</div>';
    $("analysis-meta").textContent = ""; $("lang-label").textContent = "";
    $("call-id-label").textContent = "no active call";
    $("btn-endcall").disabled = true;
    $("text-input").value = ""; $("file-input").value = "";
    $("prescreen").classList.add("hidden");
    clearAudio();
    if (clearCustomer) {
      for (const id of Object.values(FIELDS)) { if (id !== "f-agent") { $(id).value = ""; $(id).dataset.touched = "0"; } }
      state.enrichment = null; $("enrich").classList.add("hidden");
    }
    refreshLock();
  }

  $("btn-newcall").addEventListener("click", () => resetCall(true));
  $("btn-endcall").addEventListener("click", async () => {
    if (!state.callId) return;
    const outcome = prompt("Call outcome (optional): e.g. resolved / replacement sent / escalated", state.analysis?.solutions?.[state.selected[0]]?.title || "");
    if (outcome === null) return;
    try {
      await api(`/api/calls/${state.callId}/close`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ outcome, agent_notes: "" }) });
      toast("Call closed and saved.");
      await loadHistory();
      resetCall(true);
    } catch (e) { toast(e.message, true); }
  });

  // ---------------------------------------------------------------- audio player
  let playerUrl = null;
  function showAudio(blob, label) {
    if (playerUrl) URL.revokeObjectURL(playerUrl);
    playerUrl = URL.createObjectURL(blob);
    const a = $("audio-player");
    a.src = playerUrl;
    $("player-name").textContent = `${label} · ${(blob.size / 1024).toFixed(0)} KB`;
    $("player").classList.remove("hidden", "analysed");
  }
  function clearAudio() {
    if (playerUrl) URL.revokeObjectURL(playerUrl);
    playerUrl = null;
    const a = $("audio-player"); a.pause(); a.removeAttribute("src"); a.load();
    $("player").classList.add("hidden");
    state.uploadBlob = null; $("file-input").value = "";
  }
  $("player-clear").addEventListener("click", clearAudio);

  // ---------------------------------------------------------------- composer modes
  $("mode-seg").addEventListener("click", (ev) => {
    const b = ev.target.closest("button"); if (!b) return;
    state.mode = b.dataset.mode;
    [...$("mode-seg").children].forEach((x) => x.classList.toggle("active", x === b));
    for (const m of ["text", "record", "upload"]) $("mode-" + m).classList.toggle("hidden", m !== state.mode);
    $("speaker-seg").style.visibility = state.mode === "text" ? "visible" : "hidden";
  });
  $("speaker-seg").addEventListener("click", (ev) => {
    const b = ev.target.closest("button"); if (!b) return;
    state.speaker = b.dataset.speaker;
    [...$("speaker-seg").children].forEach((x) => x.classList.toggle("active", x === b));
  });

  // live pre-screen while typing (regex on the server)
  let screenTimer = null;
  $("text-input").addEventListener("input", () => {
    clearTimeout(screenTimer);
    screenTimer = setTimeout(async () => {
      const text = $("text-input").value;
      const box = $("prescreen");
      if (text.trim().length < 6) { box.classList.add("hidden"); return; }
      try {
        const r = await api("/api/screen", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
        if (r.category === "none") { box.classList.add("hidden"); return; }
        box.className = "prescreen" + (r.category === "danger" ? " danger" : "");
        box.textContent = `Pre-screen: possible ${r.category.replace("_", " ")} — matched “${r.matches[0]}”. The assistant will flag this and give handling guidance.`;
      } catch (_) { /* ignore */ }
    }, 350);
  });

  // recording
  $("btn-rec").addEventListener("click", async () => {
    if (state.recorder && state.recorder.state === "recording") { state.recorder.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      state.chunks = [];
      rec.ondataavailable = (e) => { if (e.data.size) state.chunks.push(e.data); };
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        state.uploadBlob = new Blob(state.chunks, { type: rec.mimeType || "audio/webm" });
        state.uploadBlob.name = "recording.webm";
        showAudio(state.uploadBlob, "Microphone recording");
        $("btn-rec").textContent = "● Start recording"; $("btn-rec").classList.remove("recording");
        $("rec-status").textContent = `Recorded ${(state.uploadBlob.size / 1024).toFixed(0)} KB — press Analyze.`;
      };
      rec.start();
      state.recorder = rec;
      $("btn-rec").textContent = "■ Stop recording"; $("btn-rec").classList.add("recording");
      $("rec-status").textContent = "Recording… speak, then stop.";
    } catch (e) { toast("Microphone unavailable: " + e.message, true); }
  });

  $("file-input").addEventListener("change", () => {
    const f = $("file-input").files[0];
    state.uploadBlob = f || null;
    if (f) showAudio(f, f.name); else clearAudio();
  });
  $("btn-sample").addEventListener("click", async () => {
    try {
      const res = await fetch("/api/sample-audio");
      if (!res.ok) throw new Error("sample not available");
      const blob = await res.blob();
      blob.name = "customer_call_sample.wav";
      state.uploadBlob = blob;
      $("file-input").value = "";
      showAudio(blob, "Sample call (customer_call_sample.wav)");
      toast("Sample call loaded — press Analyze.");
    } catch (e) { toast(e.message, true); }
  });

  // ---------------------------------------------------------------- analyze
  $("btn-analyze").addEventListener("click", analyze);
  $("text-input").addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") analyze(); });

  async function analyze() {
    if (state.busy || !state.customerValid) return;
    const customer = readCustomer();
    let material;
    const pendingEl = document.createElement("div");
    pendingEl.className = "bubble pending";

    try {
      setBusy(true);
      if (state.mode === "text") {
        const text = $("text-input").value.trim();
        if (!text) { toast("Type something first.", true); return; }
        material = { kind: "text", speaker: state.speaker, text, language_hint: $("lang-hint").value.trim() };
        pendingEl.innerHTML = `<span class="spinner"></span> ${esc(state.speaker)}: “${esc(text.slice(0, 120))}${text.length > 120 ? "…" : ""}”`;
      } else {
        const blob = state.uploadBlob;
        if (!blob) { toast(state.mode === "record" ? "Record something first." : "Choose an audio file first.", true); return; }
        pendingEl.innerHTML = `<span class="spinner"></span> transcribing audio locally (Whisper)…`;
        appendPending(pendingEl);
        setProgress("Transcribing with Whisper (local)…");
        const fd = new FormData();
        fd.append("file", blob, blob.name || "audio.webm");
        fd.append("language", $("lang-hint").value.trim());
        const stt = await api("/api/stt", { method: "POST", body: fd });
        if (!stt.segments.length) throw new Error("No speech detected in the audio.");
        material = { kind: "audio", speaker: "unknown", text: "", language_hint: stt.language, segments: stt.segments, voice_signal: stt.voice_signal };
        pendingEl.innerHTML = `<span class="spinner"></span> ${stt.segments.length} segments (${stt.language}) — translating &amp; analysing…`;
      }
      if (!pendingEl.isConnected) appendPending(pendingEl);
      setProgress("Analysing with Claude…");
      const body = { call_id: state.callId, customer, prior_transcript: state.transcript, new_material: material };
      const r = await api("/api/calls/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      state.callId = r.call_id;
      state.analysis = r.analysis;
      state.transcript = r.analysis.transcript;
      state.selected = r.record.selected_solutions || [];
      $("call-id-label").textContent = r.call_id;
      $("btn-endcall").disabled = false;
      $("text-input").value = ""; state.uploadBlob = null; $("file-input").value = "";
      if (material.kind === "audio") { $("player").classList.add("analysed"); $("player-name").textContent += " · analysed"; }
      $("rec-status").textContent = "Microphone recording is transcribed locally with Whisper, then analysed.";
      $("prescreen").classList.add("hidden");
      renderTranscript();
      renderAnalysis();
      if (r.usage) $("analysis-meta").textContent = `updated ${new Date().toLocaleTimeString()} · ${usageLine(r.usage)}`;
      loadHistory();
      loadHealth();
      loadUsage();
    } catch (e) {
      pendingEl.remove();
      toast(e.message, true);
    } finally {
      setProgress("");
      setBusy(false);
    }
  }

  function appendPending(el) {
    const t = $("transcript");
    const empty = t.querySelector(".empty"); if (empty) empty.remove();
    t.appendChild(el); t.scrollTop = t.scrollHeight;
  }

  // ---------------------------------------------------------------- render transcript
  function renderTranscript() {
    const t = $("transcript");
    t.innerHTML = state.transcript.map((l) => `
      <div class="bubble ${esc(l.speaker)}"><div class="who">${esc(l.speaker)}</div>${esc(l.text)}</div>`).join("");
    t.scrollTop = t.scrollHeight;
    $("lang-label").textContent = state.analysis ? `spoken language: ${state.analysis.detected_language}` : "";
  }

  // ---------------------------------------------------------------- render analysis
  const SAFETY_LABEL = { sexual_content: "Inappropriate / sexual content", danger: "Danger — safety threat", data_theft: "Data theft / social engineering", prompt_injection: "Assistant manipulation attempt", abuse: "Abusive caller", other: "Policy alert" };

  function renderAnalysis() {
    const a = state.analysis; if (!a) return;
    const level = a.priority_score >= 8 ? "l3" : a.priority_score >= 5 ? "l2" : "l1";
    const kw = (arr) => arr && arr.length ? `<div class="kw">${arr.map((k) => `<span>${esc(k)}</span>`).join("")}</div>` : "";
    const s = a.safety || { category: "none" };
    const warnIcon = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 3 2 21h20L12 3z"/><path d="M12 10v5M12 18h.01"/></svg>`;

    // 1) RED - safety / fraud / sexual content / threats: always first
    let safetyHtml = "";
    if (s.category !== "none") {
      safetyHtml = `
        <div class="box box-red">
          <div class="box-title">${warnIcon} Security alert · ${esc(SAFETY_LABEL[s.category] || s.category)}<span class="spacer"></span><span>${esc(s.severity)}</span></div>
          <p>${esc(s.description)}</p>
          ${kw(s.keywords)}
          <div class="guide"><b>What to do:</b> ${esc(s.agent_guidance)}</div>
          ${s.block_solutions ? `<div class="tiny">The request itself is not serviced. Only safe handling steps are listed below.</div>` : ""}
        </div>`;
    }

    // 2) YELLOW - the problem (+ urgent action, next question, priority thermometer)
    const problemHtml = `
      <div class="box box-yellow">
        <div class="box-title">${warnIcon} The problem<span class="spacer"></span><span class="sent ${esc(a.sentiment)}" style="padding:2px 8px"><span class="dot"></span>${esc(a.sentiment)}</span></div>
        <div class="box-yellow-grid">
          <div style="display:flex;flex-direction:column;gap:8px;min-width:0">
            <div class="problem">${esc(a.problem_statement)}</div>
            ${a.customer_goal ? `<div class="goal"><b>Wants</b>${esc(a.customer_goal)}</div>` : ""}
            ${kw(a.priority_keywords)}
            ${a.urgent_action ? `<div class="urgent"><b>Urgent action:</b> ${esc(a.urgent_action)}</div>` : ""}
            ${a.next_question ? `<div class="ask"><b>Ask next:</b> ${esc(a.next_question)}</div>` : ""}
          </div>
          <div class="thermo">
            <div class="thermo-label">Priority</div>
            <div class="thermo-score">${a.priority_score}<span class="tiny">/10</span></div>
            <div class="thermo-body">
              <div class="thermo-glass"><div class="thermo-mercury ${level}" id="mercury"></div></div>
              <div class="thermo-bulb ${level}"></div>
              <div class="thermo-scale"><span>10</span><span>5</span><span>1</span></div>
            </div>
          </div>
        </div>
      </div>`;

    // 3) BLUE - solutions the agent can offer
    const solutions = (a.solutions || []).map((sol, i) => {
      const offered = state.selected.includes(i);
      return `
        <div class="sol ${offered ? "offered" : ""}" data-i="${i}">
          <div class="t">${esc(sol.title)} <span class="tag ${esc(sol.kind)}">${esc(sol.kind.replace("_", " "))}</span>${i === a.recommended_solution_index ? '<span class="tag rec">recommended</span>' : ""}</div>
          <div class="d">${esc(sol.details)}</div>
          <div class="say"><b>Say</b>${esc(sol.suggested_phrasing)}</div>
          <div class="act"><button class="btn small ${offered ? "" : "primary"}" data-offer="${i}">${offered ? "✓ Offered" : "Offer"}</button></div>
        </div>`;
    }).join("");
    const solutionsHtml = `
      <div class="box box-blue">
        <div class="box-title">💡 ${s.block_solutions ? "Safe handling steps" : "Solutions to offer"}<span class="spacer"></span><span class="tiny">click Offer to log what you proposed</span></div>
        <div class="solutions">${solutions || '<div class="sol"><div class="d">No solutions proposed.</div></div>'}</div>
        ${a.emotional_effect ? `<div class="effect"><b>Effect</b>${esc(a.emotional_effect)}</div>` : ""}
      </div>`;

    // 4) details
    const detailsHtml = `
      <div class="vitals-strip">
        <span><span class="lab">Language</span>${esc(a.detected_language)}</span>
        <span><span class="lab">Sentiment words</span>${esc((a.sentiment_keywords || []).join(", ") || "—")}</span>
      </div>
      <div class="block"><h4>Voice tone</h4><p class="muted">${esc(a.voice_tone)}</p></div>
      <div class="block"><h4>Summary for supervisor</h4><p class="muted">${esc(a.summary)}</p></div>`;

    $("analysis").innerHTML = safetyHtml + problemHtml + solutionsHtml + detailsHtml;
    requestAnimationFrame(() => { const m = $("mercury"); if (m) m.style.height = `${a.priority_score * 10}%`; });
    $("analysis-meta").textContent = `updated ${new Date().toLocaleTimeString()}`;

    $("analysis").querySelectorAll("[data-offer]").forEach((b) => b.addEventListener("click", async () => {
      const i = Number(b.dataset.offer);
      const offered = !state.selected.includes(i);
      try {
        const r = await api(`/api/calls/${state.callId}/select`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ solution_index: i, offered }) });
        state.selected = r.selected_solutions;
        renderAnalysis();
        toast(offered ? `Logged: offered “${a.solutions[i].title}”` : "Offer removed.");
      } catch (e) { toast(e.message, true); }
    }));
  }

  // ---------------------------------------------------------------- history
  async function loadHistory() {
    try {
      const r = await api("/api/calls?limit=300");
      state.history = r.calls;
      renderHistory();
    } catch (e) { toast(e.message, true); }
  }

  function renderHistory() {
    const q = $("h-search").value.trim().toLowerCase();
    const sent = $("h-sent").value; const src = $("h-src").value;
    const rows = state.history.filter((r) => (!sent || r.sentiment === sent) && (!src || r.source === src) &&
      (!q || [r.id, r.phone, r.customer_name, r.product, r.problem, r.agent_name].join(" ").toLowerCase().includes(q)));
    const col = (p) => p >= 8 ? "var(--c-emergency)" : p >= 5 ? "var(--c-neutral)" : "var(--c-success)";
    $("history-body").innerHTML = rows.map((r, i) => `
      <tr data-id="${esc(r.id)}">
        <td class="tiny">${rows.length - i}</td>
        <td class="mono">${esc(r.date)} ${esc(r.time)}</td>
        <td>${esc(r.customer_name || "—")}</td>
        <td class="mono">${esc(r.phone)}</td>
        <td>${esc(r.product || "—")}</td>
        <td>${esc(r.language || "—")}</td>
        <td><span class="sent ${esc(r.sentiment)}"><span class="dot"></span>${esc(r.sentiment)}</span></td>
        <td><span class="pbar"><i style="--w:${(r.priority_score || 0) * 10}%;--col:${col(r.priority_score || 0)}"></i>${r.priority_score ?? "—"}</span></td>
        <td>${r.safety_category && r.safety_category !== "none" ? `<span class="badge safety ${r.safety_category === "danger" ? "danger" : ""}">${esc(r.safety_category.replace("_", " "))}</span>` : '<span class="tiny">—</span>'}</td>
        <td class="wrap">${esc((r.problem || "").slice(0, 140))}${(r.problem || "").length > 140 ? "…" : ""}</td>
        <td><span class="badge ${esc(r.source)}">${esc(r.source)}</span></td>
        <td><span class="badge ${esc(r.status)}">${esc(r.status)}</span></td>
      </tr>`).join("") || `<tr><td colspan="12" class="tiny" style="text-align:center;padding:24px">No calls match.</td></tr>`;
  }
  ["h-search", "h-sent", "h-src"].forEach((id) => $(id).addEventListener("input", renderHistory));
  $("history-body").addEventListener("click", (ev) => { const tr = ev.target.closest("tr[data-id]"); if (tr) openDrawer(tr.dataset.id); });

  $("btn-clear").addEventListener("click", async () => {
    if (!confirm("Delete all LIVE calls from the history? Demo data is kept.")) return;
    try { const r = await api("/api/calls/live", { method: "DELETE" }); toast(`Deleted ${r.deleted} live calls.`); resetCall(false); await loadHistory(); loadHealth(); }
    catch (e) { toast(e.message, true); }
  });

  $("btn-export-csv").addEventListener("click", () => {
    const cols = ["id", "date", "time", "phone", "customer_name", "agent_name", "product", "language", "sentiment", "priority_score", "safety_category", "problem", "outcome", "source", "status"];
    const csv = [cols.join(",")].concat(state.history.map((r) => cols.map((c) => `"${String(r[c] ?? "").replace(/"/g, '""')}"`).join(","))).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv" }));
    a.download = "senticall_calls.csv"; a.click();
  });

  async function openDrawer(id) {
    let rec;
    try { rec = await api(`/api/calls/${encodeURIComponent(id)}`); } catch (e) { toast(e.message, true); return; }
    const d = rec.data || {};
    const transcript = Array.isArray(d.transcript)
      ? d.transcript.map((l) => `<div class="bubble ${esc(l.speaker)}"><div class="who">${esc(l.speaker)}</div>${esc(l.text)}</div>`).join("")
      : `<pre>${esc(d.transcription || "")}</pre>`;
    const sols = (d.solutions || []).map((s, i) => `<li>${esc(typeof s === "string" ? s : s.title + " — " + s.details)}${(rec.selected_solutions || []).includes(i) ? " <span class='badge open'>offered</span>" : ""}</li>`).join("");
    const root = $("drawer-root");
    root.innerHTML = `
      <div class="drawer-root">
        <div class="drawer-back" id="drawer-back"></div>
        <div class="drawer">
          <div class="panel-head"><h2>${esc(rec.id)}</h2><span class="spacer"></span><span class="tiny">${esc(rec.date)} ${esc(rec.time)} · ${esc(rec.source || "demo")}</span><button class="btn small ghost" id="drawer-close">✕</button></div>
          <div class="drawer-body">
            <dl class="kv">
              <dt>Customer</dt><dd>${esc(rec.customer?.full_name || "—")} · ${esc(rec.phone)}</dd>
              <dt>Agent</dt><dd>${esc(rec.agent_name || "—")}</dd>
              <dt>Sentiment</dt><dd>${esc(d.sentiment)} · priority ${esc(d.priority_score)}</dd>
              <dt>Language</dt><dd>${esc(d.detected_language || d.language_type || "—")}</dd>
              ${rec.outcome ? `<dt>Outcome</dt><dd>${esc(rec.outcome)}</dd>` : ""}
            </dl>
            ${d.safety && d.safety.category !== "none" ? `<div class="safety warn"><div class="title">${esc(SAFETY_LABEL[d.safety.category] || d.safety.category)}</div><div>${esc(d.safety.description)}</div></div>` : ""}
            <div class="block"><h4>Problem</h4><p>${esc(d.problem_statement || d.summary || "")}</p></div>
            ${d.urgent_action ? `<div class="callout urgent"><b>Urgent action:</b> ${esc(d.urgent_action)}</div>` : ""}
            <div class="block"><h4>Solutions</h4><ul class="muted" style="margin:0;padding-left:18px">${sols || "<li>—</li>"}</ul></div>
            <div class="block"><h4>Transcript (English)</h4><div class="transcript" style="max-height:none">${transcript}</div></div>
            <div class="block"><h4>Summary</h4><p class="muted">${esc(d.summary || "")}</p></div>
          </div>
        </div>
      </div>`;
    const close = () => { root.innerHTML = ""; };
    $("drawer-back").addEventListener("click", close);
    $("drawer-close").addEventListener("click", close);
    document.addEventListener("keydown", function onKey(e) { if (e.key === "Escape") { close(); document.removeEventListener("keydown", onKey); } });
  }

  // ---------------------------------------------------------------- views
  document.querySelector(".nav").addEventListener("click", (ev) => {
    const b = ev.target.closest("button"); if (!b) return;
    document.querySelectorAll(".nav button").forEach((x) => x.classList.toggle("active", x === b));
    const v = b.dataset.view;
    $("view-live").classList.toggle("hidden", v !== "live");
    $("view-analytics").classList.toggle("hidden", v !== "analytics");
    if (v === "analytics") loadDashboard();
  });

  // ---------------------------------------------------------------- analytics
  const SENT_COLORS = { Negative: "oklch(62% 0.21 25)", Neutral: "oklch(76% 0.14 68)", Positive: "oklch(72% 0.17 150)" };
  const ORDER = ["Negative", "Neutral", "Positive"];
  const GRID = "oklch(25% 0.014 215)", TICK = "oklch(68% 0.01 215)";

  Chart.defaults.color = TICK;
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 11;

  const lettersPlugin = {
    id: "letters",
    afterDatasetsDraw(chart) {
      const letters = chart.config.options.letters; if (!letters) return;
      const { ctx } = chart;
      ctx.save(); ctx.font = "600 10px " + Chart.defaults.font.family; ctx.textAlign = "center"; ctx.fillStyle = "oklch(93% 0.006 215)";
      chart.data.datasets.forEach((ds, di) => {
        const meta = chart.getDatasetMeta(di);
        meta.data.forEach((bar, i) => {
          const cat = chart.data.labels[i]; const v = ds.data[i];
          if (v == null) return;
          const suf = letters[cat]?.[ds.label] || "";
          ctx.fillText(`${Math.round(v)}%${suf ? " " + suf : ""}`, bar.x, bar.y - 4);
        });
      });
      ctx.restore();
    },
  };

  function mkChart(id, cfg) {
    if (state.charts[id]) state.charts[id].destroy();
    cfg.options = Object.assign({ responsive: true, maintainAspectRatio: false, animation: { duration: 300 } }, cfg.options || {});
    state.charts[id] = new Chart($(id).getContext("2d"), cfg);
  }

  async function loadDashboard() {
    try {
      const d = await api("/api/analytics/dashboard");
      state.dash = d;
      if (!d.kpis) { $("kpis").innerHTML = '<div class="kpi"><div class="l">No data</div></div>'; return; }
      const k = d.kpis;
      $("kpis").innerHTML = [
        ["Calls analysed", `${k.total_calls}<small>${k.live_calls} live · ${k.demo_calls} demo</small>`],
        ["Negative sentiment", `${k.negative_pct}%`],
        ["Average priority", `${k.avg_priority}<small>/10</small>`],
        ["High priority (≥8)", `${k.high_priority_pct}%`],
        ["Safety alerts", `${k.safety_alerts}`],
        ["Open calls", `${k.open_calls}`],
        ["Matched to profile", `${k.matched_demographics}<small>of ${k.total_calls}</small>`],
      ].map(([l, v]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div></div>`).join("");
      $("n-total").textContent = `n = ${k.total_calls}`;

      mkChart("c-pie", { type: "doughnut", data: { labels: ORDER, datasets: [{ data: ORDER.map((s) => d.overall_sentiment[s]), backgroundColor: ORDER.map((s) => SENT_COLORS[s]), borderColor: "oklch(15.5% 0.01 215)", borderWidth: 2 }] },
        options: { cutout: "58%", plugins: { legend: { position: "right" }, tooltip: { callbacks: { label: (c) => ` ${c.label}: ${c.parsed}%` } } } } });

      for (const col of ["gender", "ageGroup", "incomeGroup2", "education"]) {
        const g = d.by_group[col];
        mkChart("c-" + col, { type: "bar", plugins: [lettersPlugin],
          data: { labels: g.categories, datasets: ORDER.map((s) => ({ label: s, data: g.series[s], backgroundColor: SENT_COLORS[s], borderRadius: 3, maxBarThickness: 34 })) },
          options: { letters: g.letters, scales: { y: { min: 0, max: 110, ticks: { callback: (v) => v <= 100 ? v + "%" : "" }, grid: { color: GRID } }, x: { grid: { display: false }, ticks: { callback: (v, i) => `${g.categories[i]} (n=${g.counts[g.categories[i]]})` } } },
            plugins: { legend: { position: "bottom" }, tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${c.parsed.y}%` } } } } });
      }

      for (const [key, id] of [["month", "c-month"], ["day_of_week", "c-day_of_week"], ["hour", "c-hour"]]) {
        const t = d.by_time[key];
        mkChart(id, { type: "line",
          data: { labels: t.categories, datasets: ORDER.map((s) => ({ label: s, data: t.series[s], borderColor: SENT_COLORS[s], backgroundColor: SENT_COLORS[s], tension: 0.25, pointRadius: 3, spanGaps: false })) },
          options: { scales: { y: { min: 0, max: 100, ticks: { callback: (v) => v + "%" }, grid: { color: GRID } }, x: { grid: { display: false } } },
            plugins: { legend: { position: "bottom" }, tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${c.parsed.y}% (n=${t.counts[c.dataIndex]})` } } } } });
      }

      const pd = d.priority_distribution;
      mkChart("c-priority", { type: "bar", data: { labels: Object.keys(pd), datasets: [{ label: "calls", data: Object.values(pd), backgroundColor: Object.keys(pd).map((k) => k >= 8 ? SENT_COLORS.Negative : k >= 5 ? SENT_COLORS.Neutral : SENT_COLORS.Positive), borderRadius: 3 }] },
        options: { scales: { y: { beginAtZero: true, grid: { color: GRID }, ticks: { precision: 0 } }, x: { grid: { display: false }, title: { display: true, text: "priority score" } } }, plugins: { legend: { display: false } } } });

      const th = d.issue_themes;
      mkChart("c-themes", { type: "bar", data: { labels: th.map((t) => t.theme), datasets: [{ label: "calls", data: th.map((t) => t.count), backgroundColor: "oklch(78% 0.13 200)", borderRadius: 3 }] },
        options: { indexAxis: "y", scales: { x: { beginAtZero: true, grid: { color: GRID }, ticks: { precision: 0 } }, y: { grid: { display: false } } }, plugins: { legend: { display: false } } } });
    } catch (e) { toast(e.message, true); }
  }

  function renderInsights(ins, cached) {
    const list = (arr) => `<ul>${(arr || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
    $("insights-body").className = "insights-grid";
    $("insights-body").innerHTML = `
      <div>
        <h4>Executive summary</h4><p>${esc(ins.executive_summary)}</p>
        <h4>Key findings</h4>${list(ins.key_findings)}
        <h4>Executive action plan</h4><p>${esc(ins.executive_action_plan)}</p>
      </div>
      <div>
        <h4>Staffing recommendations</h4>${list(ins.staffing_recommendations)}
        <h4>Demographic support insights</h4>${list(ins.demographic_support_insights)}
        <h4>Technical friction areas</h4>${list(ins.technical_friction_areas)}
        <h4>Operational priorities</h4>${list(ins.operational_priorities)}
      </div>`;
    $("insights-meta").textContent = cached ? "cached for this data" : `generated ${new Date().toLocaleTimeString()}`;
  }

  $("btn-insights").addEventListener("click", async () => {
    const b = $("btn-insights"); b.disabled = true; const old = b.textContent; b.innerHTML = '<span class="spinner"></span> Generating…';
    try {
      const r = await api("/api/report/insights", { method: "POST" }); state.insights = r.insights; renderInsights(r.insights, r.cached);
      if (r.usage) { $("insights-meta").textContent += ` · ${usageLine(r.usage)}`; loadUsage(); }
    }
    catch (e) { toast(e.message, true); }
    finally { b.disabled = false; b.textContent = old; }
  });

  $("btn-pptx").addEventListener("click", async () => {
    const b = $("btn-pptx"); b.disabled = true; const old = b.textContent; b.innerHTML = '<span class="spinner"></span> Building…';
    try {
      const r = await api("/api/report/pptx", { method: "POST" });
      const a = document.createElement("a"); a.href = r.url; a.download = r.file; a.click();
      toast(r.with_insights ? "PowerPoint exported with AI insights." : "PowerPoint exported (charts only — generate insights first to include them).");
    } catch (e) { toast(e.message, true); }
    finally { b.disabled = false; b.textContent = old; }
  });

  // ---------------------------------------------------------------- boot
  refreshLock();
  loadHealth();
  loadHistory();
  loadUsage();
})();
