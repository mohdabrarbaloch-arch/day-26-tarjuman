/* Tarjuman — front-end.
   Vanilla JS, no build step. The whole app is one page with three views, so a
   framework would be more machinery than the problem needs. */

(() => {
  "use strict";

  // ---------- state ----------
  const state = {
    token: localStorage.getItem("tarjuman_token") || null,
    user: null,
    languages: [],
    view: "translate",
    lastResult: null,
    historyOffset: 0,
    historyTotal: 0,
    conversation: null,
    speaker: "a",
  };

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };

  // ---------- api ----------
  async function api(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;

    const res = await fetch(path, { ...options, headers });
    let body = null;
    if (res.status !== 204) {
      const text = await res.text();
      if (text) {
        try { body = JSON.parse(text); } catch { body = { detail: { message: text } }; }
      }
    }
    if (!res.ok) {
      const detail = body && body.detail;
      const message =
        (detail && detail.message) ||
        (typeof detail === "string" ? detail : null) ||
        `Request failed (${res.status})`;
      const err = new Error(message);
      err.status = res.status;
      err.code = detail && detail.code;
      throw err;
    }
    return body;
  }

  // ---------- toast ----------
  let toastTimer = null;
  function toast(message) {
    const t = $("toast");
    t.textContent = message;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 2600);
  }

  // ---------- languages ----------
  async function loadLanguages() {
    try {
      state.languages = await api("/api/languages");
    } catch {
      state.languages = [
        { code: "en", name: "English", native_name: "English", rtl: false },
        { code: "ur", name: "Urdu", native_name: "اردو", rtl: true },
      ];
    }
    const opts = state.languages
      .map((l) => `<option value="${l.code}">${l.name} — ${l.native_name}</option>`)
      .join("");

    $("sourceLang").innerHTML = `<option value="auto">Detect language</option>` + opts;
    $("targetLang").innerHTML = opts;
    $("convLangA").innerHTML = opts;
    $("convLangB").innerHTML = opts;

    $("sourceLang").value = "auto";
    $("targetLang").value = "ur";
    $("convLangA").value = "en";
    $("convLangB").value = "ur";
  }

  function langName(code) {
    const l = state.languages.find((x) => x.code === code);
    return l ? l.name : code;
  }

  function isRtl(code) {
    const l = state.languages.find((x) => x.code === code);
    return !!(l && l.rtl);
  }

  // ---------- views ----------
  function setView(name) {
    state.view = name;
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("is-active"));
    const target = $(`view-${name}`);
    if (target) target.classList.add("is-active");
    document.querySelectorAll(".nav-btn").forEach((b) => {
      b.classList.toggle("is-active", b.dataset.view === name);
    });
    if (name === "history") loadHistory(true);
  }

  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => setView(btn.dataset.view));
  });

  // ---------- auth ----------
  let authMode = "login";

  function setAuthMode(mode) {
    authMode = mode;
    const isRegister = mode === "register";
    $("authTitle").textContent = isRegister ? "Create an account" : "Sign in";
    $("authSub").textContent = isRegister
      ? "Save your translations and conversations."
      : "Welcome back.";
    $("authSubmit").textContent = isRegister ? "Create account" : "Sign in";
    $("nameField").hidden = !isRegister;
    $("switchText").textContent = isRegister ? "Already have an account?" : "No account?";
    $("switchMode").textContent = isRegister ? "Sign in" : "Create one";
    $("authPassword").autocomplete = isRegister ? "new-password" : "current-password";
    $("authError").hidden = true;
  }

  function openAuth(mode = "login") {
    setAuthMode(mode);
    $("authModal").hidden = false;
    setTimeout(() => $("authEmail").focus(), 60);
  }

  function closeAuth() {
    $("authModal").hidden = true;
    $("authForm").reset();
    $("authError").hidden = true;
  }

  document.querySelectorAll("[data-close]").forEach((n) => n.addEventListener("click", closeAuth));
  $("switchMode").addEventListener("click", () => setAuthMode(authMode === "login" ? "register" : "login"));
  $("signInBtn").addEventListener("click", () => {
    if (state.user) {
      signOut();
    } else {
      openAuth("login");
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("authModal").hidden) closeAuth();
  });

  $("authForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errBox = $("authError");
    errBox.hidden = true;
    const submit = $("authSubmit");
    submit.disabled = true;

    const payload = {
      email: $("authEmail").value.trim(),
      password: $("authPassword").value,
    };
    if (authMode === "register") payload.display_name = $("authName").value.trim();

    try {
      const path = authMode === "register" ? "/api/auth/register" : "/api/auth/login";
      const data = await api(path, { method: "POST", body: JSON.stringify(payload) });
      state.token = data.access_token;
      state.user = data.user;
      localStorage.setItem("tarjuman_token", data.access_token);
      closeAuth();
      renderAuthSlot();
      toast(authMode === "register" ? "Account created." : `Welcome back, ${data.user.display_name}.`);
      if (state.view === "history") loadHistory(true);
    } catch (err) {
      errBox.textContent = err.message;
      errBox.hidden = false;
    } finally {
      submit.disabled = false;
    }
  });

  function signOut() {
    state.token = null;
    state.user = null;
    localStorage.removeItem("tarjuman_token");
    renderAuthSlot();
    toast("Signed out.");
    if (state.view === "history") loadHistory(true);
  }

  function renderAuthSlot() {
    const slot = $("authSlot");
    slot.innerHTML = "";
    if (state.user) {
      const name = state.user.display_name || state.user.email.split("@")[0];
      const btn = el("button", "btn btn-ghost btn-sm", name);
      btn.type = "button";
      btn.title = "Sign out";
      btn.addEventListener("click", signOut);
      slot.appendChild(btn);
    } else {
      const btn = el("button", "btn btn-ghost btn-sm", "Sign in");
      btn.type = "button";
      btn.addEventListener("click", () => openAuth("login"));
      slot.appendChild(btn);
    }
  }

  async function restoreSession() {
    if (!state.token) return;
    try {
      state.user = await api("/api/auth/me");
    } catch {
      state.token = null;
      localStorage.removeItem("tarjuman_token");
    }
    renderAuthSlot();
  }

  // ---------- translate ----------
  const sourceText = $("sourceText");
  const charCount = $("charCount");

  function updateCounter() {
    const n = sourceText.value.length;
    charCount.textContent = `${n} / 5000`;
    charCount.classList.toggle("over", n > 5000);
  }
  sourceText.addEventListener("input", updateCounter);

  $("clearBtn").addEventListener("click", () => {
    sourceText.value = "";
    updateCounter();
    $("outputBody").innerHTML = '<p class="placeholder">Your translation will appear here, with its verdict.</p>';
    $("verdictPanel").hidden = true;
    $("copyBtn").hidden = true;
    $("saveBtn").hidden = true;
    state.lastResult = null;
  });

  const SAMPLES = [
    { text: "Please send the invoice by Friday so we can process the payment.", from: "en", to: "ur" },
    { text: "Mujhe kal subah office jana hai, meeting nau baje hai.", from: "ur", to: "en" },
    { text: "Aaj mausam bohat acha hai, chalein bahar chalte hain.", from: "ur", to: "en" },
    { text: "The quarterly report is ready for review. Let me know your thoughts.", from: "en", to: "es" },
  ];
  let sampleIndex = 0;

  $("sampleBtn").addEventListener("click", () => {
    const s = SAMPLES[sampleIndex % SAMPLES.length];
    sampleIndex++;
    sourceText.value = s.text;
    $("sourceLang").value = s.from;
    $("targetLang").value = s.to;
    updateCounter();
    sourceText.focus();
  });

  $("swapBtn").addEventListener("click", () => {
    const from = $("sourceLang").value;
    const to = $("targetLang").value;
    if (from === "auto") {
      toast("Pick a source language first, then swap.");
      return;
    }
    $("sourceLang").value = to;
    $("targetLang").value = from;
    const btn = $("swapBtn");
    btn.classList.toggle("spin");
    setTimeout(() => btn.classList.remove("spin"), 220);
  });

  $("translateBtn").addEventListener("click", doTranslate);
  sourceText.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") doTranslate();
  });

  async function doTranslate() {
    const text = sourceText.value.trim();
    if (!text) {
      toast("Type something to translate first.");
      sourceText.focus();
      return;
    }

    const btn = $("translateBtn");
    const label = btn.querySelector(".btn-label");
    const spinner = btn.querySelector(".spinner");
    btn.disabled = true;
    label.textContent = "Translating…";
    spinner.hidden = false;

    try {
      const result = await api("/api/translate", {
        method: "POST",
        body: JSON.stringify({
          text,
          source_lang: $("sourceLang").value,
          target_lang: $("targetLang").value,
          round_trip: $("roundTripToggle").checked,
          save: false,
        }),
      });
      state.lastResult = result;
      renderResult(result);
    } catch (err) {
      $("outputBody").innerHTML = "";
      const p = el("p", "placeholder", err.message);
      $("outputBody").appendChild(p);
      $("verdictPanel").hidden = true;
      toast(err.message);
    } finally {
      btn.disabled = false;
      label.textContent = "Translate";
      spinner.hidden = true;
    }
  }

  function renderResult(r) {
    const body = $("outputBody");
    body.innerHTML = "";
    const p = el("p", "out-text", r.translated_text);
    if (r.target_rtl) p.setAttribute("dir", "rtl");
    body.appendChild(p);

    $("copyBtn").hidden = false;
    $("saveBtn").hidden = !state.user;

    renderVerdict(r);
  }

  const VERDICT_LABEL = {
    verified: "Verified",
    likely: "Likely correct",
    uncertain: "Uncertain",
    failed: "Failed",
  };

  const AXIS_LABEL = {
    script: "Script conformance",
    echo: "Echo detection",
    length: "Length plausibility",
    transliteration: "Transliteration check",
    round_trip: "Round-trip fidelity",
  };

  function renderVerdict(r) {
    const panel = $("verdictPanel");
    const v = r.verification;
    panel.innerHTML = "";

    const head = el("div", "verdict-head");
    const badge = el("span", `verdict-badge v-${v.verdict}`);
    badge.appendChild(el("span", "dot"));
    badge.appendChild(document.createTextNode(VERDICT_LABEL[v.verdict] || v.verdict));
    head.appendChild(badge);

    head.appendChild(el("span", "verdict-summary", r.summary));

    const conf = el("div", "confidence");
    conf.appendChild(document.createTextNode("confidence"));
    const bar = el("div", "conf-bar");
    const fill = el("div", "conf-fill");
    fill.style.width = `${Math.round(v.confidence * 100)}%`;
    fill.style.background =
      v.verdict === "verified" ? "var(--ok)" :
      v.verdict === "likely" ? "var(--info)" :
      v.verdict === "uncertain" ? "var(--warn)" : "var(--fail)";
    bar.appendChild(fill);
    conf.appendChild(bar);
    conf.appendChild(document.createTextNode(`${Math.round(v.confidence * 100)}%`));
    head.appendChild(conf);
    panel.appendChild(head);

    const axes = el("div", "axes");
    v.findings.forEach((f) => {
      const row = el("div", "axis");
      const name = el("div", "axis-name");
      const mark = el("span", `axis-mark m-${f.severity}`);
      mark.textContent = f.severity === "ok" ? "✓" : f.severity === "warn" ? "!" : "✕";
      name.appendChild(mark);
      name.appendChild(document.createTextNode(AXIS_LABEL[f.axis] || f.axis));
      row.appendChild(name);
      row.appendChild(el("span", "axis-score", f.score.toFixed(2)));
      row.appendChild(el("p", "axis-reason", f.reason));
      axes.appendChild(row);
    });
    panel.appendChild(axes);

    // Chunk-level detail, only when the text was split.
    if (r.chunks && r.chunks.length > 1) {
      const failed = r.chunks.filter((c) => c.verification.verdict === "failed").length;
      const note = el("div", "chunk-note");
      const strong = el("strong");
      strong.textContent = `${r.chunks.length} chunks`;
      note.appendChild(strong);
      note.appendChild(
        document.createTextNode(
          failed > 0
            ? ` — ${failed} of them failed verification. Scroll the translation to find the bad section.`
            : " — every chunk passed on its own."
        )
      );
      panel.appendChild(note);
    }

    if (r.roman_urdu_source) {
      const note = el("div", "chunk-note");
      const strong = el("strong");
      strong.textContent = "Roman Urdu detected. ";
      note.appendChild(strong);
      note.appendChild(
        document.createTextNode(
          "Your text is Urdu written in Latin letters. The provider has no code for that, " +
          "so it was sent as Urdu — and the transliteration check is what catches it if the " +
          "provider only respells the words instead of translating them."
        )
      );
      panel.appendChild(note);
    }

    panel.hidden = false;
  }

  $("copyBtn").addEventListener("click", async () => {
    if (!state.lastResult) return;
    try {
      await navigator.clipboard.writeText(state.lastResult.translated_text);
      toast("Copied.");
    } catch {
      toast("Could not copy — select the text manually.");
    }
  });

  $("saveBtn").addEventListener("click", async () => {
    if (!state.lastResult || !state.user) return;
    const r = state.lastResult;
    try {
      await api("/api/translate", {
        method: "POST",
        body: JSON.stringify({
          text: r.source_text,
          source_lang: r.source_lang,
          target_lang: r.target_lang,
          round_trip: false,
          save: true,
        }),
      });
      toast("Saved to history.");
    } catch (err) {
      toast(err.message);
    }
  });

  // ---------- conversation ----------
  $("startConvBtn").addEventListener("click", async () => {
    const a = $("convLangA").value;
    const b = $("convLangB").value;
    if (a === b) {
      toast("Pick two different languages.");
      return;
    }
    if (!state.user) {
      openAuth("login");
      toast("Sign in to start a conversation.");
      return;
    }
    try {
      const conv = await api("/api/conversations", {
        method: "POST",
        body: JSON.stringify({ title: "Conversation", lang_a: a, lang_b: b }),
      });
      state.conversation = conv;
      openConversation(conv);
    } catch (err) {
      toast(err.message);
    }
  });

  function openConversation(conv) {
    $("convSetup").hidden = true;
    $("convActive").hidden = false;
    $("convTitle").textContent = conv.title || "Conversation";
    $("convLangs").textContent = `${langName(conv.lang_a)} ↔ ${langName(conv.lang_b)}`;
    $("spkA").textContent = conv.lang_a.toUpperCase();
    $("spkB").textContent = conv.lang_b.toUpperCase();
    $("transcript").innerHTML = "";
    state.speaker = "a";
    setSpeaker("a");
    renderTurns(conv.turns || []);
    $("convInput").focus();
  }

  function setSpeaker(s) {
    state.speaker = s;
    $("spkA").classList.toggle("is-active", s === "a");
    $("spkB").classList.toggle("is-active", s === "b");
  }

  $("spkA").addEventListener("click", () => setSpeaker("a"));
  $("spkB").addEventListener("click", () => setSpeaker("b"));

  function renderTurns(turns) {
    const box = $("transcript");
    turns.forEach((t) => box.appendChild(renderTurn(t)));
    box.scrollTop = box.scrollHeight;
  }

  function renderTurn(t) {
    const wrap = el("div", `turn turn-${t.speaker}`);
    wrap.appendChild(el("div", "turn-orig", t.original_text));

    const trans = el("div", "turn-trans", t.translated_text);
    if (isRtl(t.target_lang)) trans.setAttribute("dir", "rtl");
    wrap.appendChild(trans);

    if (t.verdict && t.verdict !== "verified") {
      const flag = el("div", `turn-flag ${t.verdict === "failed" ? "fail" : "warn"}`);
      flag.textContent =
        t.verdict === "failed"
          ? "⚠ this turn did not translate — read the original"
          : "⚠ check this turn before relying on it";
      wrap.appendChild(flag);
    }
    return wrap;
  }

  async function sendTurn() {
    const input = $("convInput");
    const text = input.value.trim();
    if (!text || !state.conversation) return;

    const btn = $("sendTurnBtn");
    btn.disabled = true;
    input.disabled = true;

    try {
      const turn = await api(`/api/conversations/${state.conversation.id}/turns`, {
        method: "POST",
        body: JSON.stringify({ speaker: state.speaker, text }),
      });
      $("transcript").appendChild(renderTurn(turn));
      $("transcript").scrollTop = $("transcript").scrollHeight;
      input.value = "";
      // Flip the speaker: in a real conversation the other person replies next.
      setSpeaker(state.speaker === "a" ? "b" : "a");
    } catch (err) {
      toast(err.message);
    } finally {
      btn.disabled = false;
      input.disabled = false;
      input.focus();
    }
  }

  $("sendTurnBtn").addEventListener("click", sendTurn);
  $("convInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); sendTurn(); }
  });

  $("endConvBtn").addEventListener("click", () => {
    state.conversation = null;
    $("convActive").hidden = true;
    $("convSetup").hidden = false;
    $("transcript").innerHTML = "";
  });

  // ---------- history ----------
  async function loadHistory(reset = false) {
    const list = $("historyList");
    if (!state.user) {
      list.innerHTML = "";
      const empty = el("div", "empty");
      empty.textContent = "Sign in to see your saved translations.";
      list.appendChild(empty);
      $("loadMoreBtn").hidden = true;
      return;
    }

    if (reset) {
      state.historyOffset = 0;
      list.innerHTML = "";
    }

    const params = new URLSearchParams({
      limit: "20",
      offset: String(state.historyOffset),
    });
    if ($("favOnly").checked) params.set("favourites_only", "true");
    const verdict = $("verdictFilter").value;
    if (verdict) params.set("verdict", verdict);

    try {
      const page = await api(`/api/history?${params}`);
      state.historyTotal = page.total;

      if (page.items.length === 0 && state.historyOffset === 0) {
        list.innerHTML = "";
        const empty = el("div", "empty");
        empty.textContent = "Nothing saved yet. Translate something and hit the save icon.";
        list.appendChild(empty);
      }

      page.items.forEach((item) => list.appendChild(renderHistoryItem(item)));
      state.historyOffset += page.items.length;
      $("loadMoreBtn").hidden = state.historyOffset >= state.historyTotal;
    } catch (err) {
      toast(err.message);
    }
  }

  function renderHistoryItem(item) {
    const wrap = el("div", "hist-item");

    const top = el("div", "hist-top");
    const badge = el("span", `verdict-badge v-${item.verdict}`);
    badge.appendChild(el("span", "dot"));
    badge.textContent = "";
    badge.appendChild(el("span", "dot"));
    badge.appendChild(document.createTextNode(VERDICT_LABEL[item.verdict] || item.verdict));
    top.appendChild(badge);
    top.appendChild(el("span", "hist-pair", `${item.source_lang} → ${item.target_lang}`));
    top.appendChild(el("span", "", new Date(item.created_at).toLocaleString()));

    const actions = el("div", "hist-actions");
    const fav = el("button", "icon-btn");
    fav.type = "button";
    fav.title = item.is_favourite ? "Remove from favourites" : "Add to favourites";
    fav.textContent = item.is_favourite ? "★" : "☆";
    fav.addEventListener("click", async () => {
      try {
        await api(`/api/history/${item.id}/favourite`, {
          method: "PATCH",
          body: JSON.stringify({ is_favourite: !item.is_favourite }),
        });
        loadHistory(true);
      } catch (err) { toast(err.message); }
    });
    actions.appendChild(fav);

    const del = el("button", "icon-btn");
    del.type = "button";
    del.title = "Delete";
    del.textContent = "×";
    del.addEventListener("click", async () => {
      try {
        await api(`/api/history/${item.id}`, { method: "DELETE" });
        loadHistory(true);
        toast("Deleted.");
      } catch (err) { toast(err.message); }
    });
    actions.appendChild(del);
    top.appendChild(actions);

    wrap.appendChild(top);
    wrap.appendChild(el("p", "hist-src", item.source_text));
    const tgt = el("p", "hist-tgt", item.translated_text);
    if (isRtl(item.target_lang)) tgt.setAttribute("dir", "rtl");
    wrap.appendChild(tgt);
    return wrap;
  }

  $("favOnly").addEventListener("change", () => loadHistory(true));
  $("verdictFilter").addEventListener("change", () => loadHistory(true));
  $("loadMoreBtn").addEventListener("click", () => loadHistory(false));

  // ---------- boot ----------
  async function boot() {
    updateCounter();
    await loadLanguages();
    await restoreSession();
    setView("translate");
  }

  boot();
})();
