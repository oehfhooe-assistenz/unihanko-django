(function () {
  "use strict";

  /* =========================
   * HELP FAB + OVERLAY
   * ========================= */
  function inAdminHelpPage() { return location.pathname.startsWith("/admin/help/"); }

  function getAppModelFromBody() {
    const classes = (document.body.className || "").split(/\s+/);
    let app = null, model = null;
    for (const c of classes) {
      if (c.startsWith("app-")) app = c.slice(4);
      if (c.startsWith("model-")) model = c.slice(6);
    }
    return { app, model };
  }

  function targetHelpUrl() {
    const { app, model } = getAppModelFromBody();
    if (app && model) return `/admin/help/${app}/${model}/`;
    return `/admin/help/`;
  }

  function ensureOverlay() {
    if (document.getElementById("uh-help-overlay")) return;
    const overlay = document.createElement("div");
    overlay.id = "uh-help-overlay";
    overlay.innerHTML = `
      <div id="uh-help-box">
        <div class="uh-help-head">
          <strong>Help</strong>
          <button type="button" class="uh-help-close" aria-label="Close">×</button>
        </div>
        <div class="uh-help-body">Loading…</div>
      </div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener("click", (e) => { if (e.target.id === "uh-help-overlay") closeOverlay(); });
    overlay.addEventListener("click", (e) => { if (e.target && e.target.classList.contains("uh-help-close")) closeOverlay(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeOverlay(); });
  }

  function openOverlayWith(url) {
    ensureOverlay();
    const overlay = document.getElementById("uh-help-overlay");
    const body = overlay.querySelector(".uh-help-body");
    overlay.style.display = "flex";
    body.textContent = "Loading…";
    fetch(url + (url.includes("?") ? "&" : "?") + "fragment=1", { credentials: "same-origin" })
      .then((r) => r.text())
      .then((html) => { body.innerHTML = html; })
      .catch(() => { body.textContent = "Failed to load help."; });
  }

  function closeOverlay() {
    const overlay = document.getElementById("uh-help-overlay");
    if (overlay) overlay.style.display = "none";
  }

  function injectFab() {
    if (inAdminHelpPage()) return;
    if (document.getElementById("uh-help-fab")) return;
    const a = document.createElement("a");
    a.id = "uh-help-fab";
    a.href = targetHelpUrl();
    a.title = "Help";
    a.setAttribute("aria-label", "Help");
    a.textContent = "?";
    a.addEventListener("click", function (e) { e.preventDefault(); openOverlayWith(this.href); });
    document.body.appendChild(a);
  }

  /* =========================
   * UNSAVED CHANGES GUARD
   * ========================= */
  function installUnsavedGuard() {
    if (window.__UH_GUARD_INSTALLED__) return;
    window.__UH_GUARD_INSTALLED__ = true;

    let dirty = false;
    const markDirty = () => { dirty = true; };

    document.addEventListener("input", markDirty, true);
    document.addEventListener("change", markDirty, true);
    document.addEventListener("submit", (e) => { if (e.target && e.target.closest("form")) dirty = false; }, true);

    document.addEventListener("click", function (e) {
      const a = e.target && e.target.closest("a[href]");
      if (!a) return;
      const href = a.getAttribute("href");
      if (!href) return;
      if (href.startsWith("#") || href.startsWith("javascript:")) return;
      if ((a.target || "").toLowerCase() === "_blank") return;
      const url = new URL(href, location.href);
      if (url.origin !== location.origin) return;
      if (a.hasAttribute("data-no-guard")) return;

      if (dirty) {
        const ok = confirm("You have unsaved changes. Leave this page?");
        if (!ok) { e.preventDefault(); e.stopImmediatePropagation(); return; }
        dirty = false;
      }
    }, true);

    window.addEventListener("beforeunload", function (e) {
      if (!dirty) return;
      e.preventDefault();
      e.returnValue = "";
    });

    window.UH_CLEAR_UNSAVED_GUARD = () => { dirty = false; };
  }

  /* =========================
   * FULLCALENDAR LOADER
   * ========================= */
  function loadCSS(urls, cb) {
    (function tryNext(i) {
      if (i >= urls.length) return cb(new Error("All CSS candidates failed"));
      const href = urls[i];
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = href;
      link.onload = () => cb(null, href);
      link.onerror = () => tryNext(i + 1);
      document.head.appendChild(link);
    })(0);
  }

  function loadJS(urls, cb) {
    (function tryNext(i) {
      if (i >= urls.length) return cb(new Error("All JS candidates failed"));
      const src = urls[i];
      const s = document.createElement("script");
      s.src = src;
      s.defer = true;
      s.onload = () => cb(null, src);
      s.onerror = () => tryNext(i + 1);
      document.head.appendChild(s);
    })(0);
  }

  /* =========================
   * TIMESHEET CAL + MODAL (with i18n)
   * ========================= */
  function initCalendar() {
    const el = document.getElementById("ts-calendar");
    if (!el) return;
    if (el.dataset.uhInit === "1") return;
    el.dataset.uhInit = "1";

    const eventsUrl  = el.getAttribute("data-events-url");
    const createUrl  = el.getAttribute("data-create-url");
    const updateBase = el.getAttribute("data-update-url");
    const deleteBase = el.getAttribute("data-delete-url");
    const totalsUrl  = el.getAttribute("data-totals-url");
    const initial    = el.getAttribute("data-initial") || new Date().toISOString().slice(0, 10);
    const height     = parseInt(el.getAttribute("data-height") || "720", 10);

    // i18n helpers
    const T = (key, fallback) => el.getAttribute("data-i18n-" + key) || fallback;
    const i18n = {
      titleNew:        T("title-new",        "New entry"),
      titleEdit:       T("title-edit",       "Edit entry"),
      labelDate:       T("label-date",       "Date"),
      labelKind:       T("label-kind",       "Kind"),
      labelFrom:       T("label-from",       "From"),
      labelTo:         T("label-to",         "To"),
      labelComment:    T("label-comment",    "Comment"),
      btnSave:         T("btn-save",         "Save"),
      btnCancel:       T("btn-cancel",       "Cancel"),
      btnDelete:       T("btn-delete",       "Delete"),
      confirmDelete:   T("confirm-delete",   "Delete this entry?"),
      errTimeOrder:    T("err-time-order",   "‘To’ must be after ‘From’ (same day)."),
    };

    // CSRF helper
    function getCookie(name) {
      const m = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
      return m ? decodeURIComponent(m[2]) : null;
    }
    const csrf = getCookie("csrftoken");

    const ini  = new Date(initial);
    const last = new Date(ini.getFullYear(), ini.getMonth() + 1, 0);
    const endExclusive = new Date(last); endExclusive.setDate(last.getDate() + 1);

    const cssCandidates = [
      "/static/vendors/fullcalendar/index.global.min.css",
      "/static/vendors/fullcalendar/main.min.css",
      "https://cdn.jsdelivr.net/npm/fullcalendar@6.1.14/index.global.min.css",
    ];
    const jsCandidates = [
      "/static/vendors/fullcalendar/index.global.min.js",
      "/static/vendors/fullcalendar/index.global.js",
      "/static/vendors/fullcalendar/main.min.js",
      "https://cdn.jsdelivr.net/npm/fullcalendar@6.1.14/index.global.min.js",
    ];

    function refreshTotals() {
      if (!totalsUrl) return;
      fetch(totalsUrl, { credentials: "same-origin" })
        .then(r => r.json())
        .then(({ total, expected, delta }) => {
          const box = document.querySelector('[id$="totals_preview"]');
          if (box) {
            box.innerHTML =
`<pre style="margin:.5rem 0; font-size:12px;">total: ${total} min
expected: ${expected} min
delta: ${delta} min</pre>`;
          }
        });
    }

    /* ---------- Modal UI (create/edit) ---------- */
    function ensureModal() {
      if (document.getElementById("uh-ts-modal")) return;

      const style = document.createElement("style");
      style.textContent = `
#uh-ts-modal{position:fixed;inset:0;background:rgba(0,0,0,.45);display:none;align-items:center;justify-content:center;z-index:9999;}
#uh-ts-card{background:#12161b;color:#e5e7eb;border:1px solid #232a32;border-radius:8px;min-width:320px;max-width:420px;padding:16px;box-shadow:0 10px 30px rgba(0,0,0,.5);}
#uh-ts-card h3{margin:0 0 12px;font-size:16px; color: #ff8a3d;}
#uh-ts-form label{display:block;font-size:12px;color:#ff8a3d;margin:8px 0 6px;}
#uh-ts-form input, #uh-ts-form select{width:100%;background:#fff;border:1px solid #ced4da;border-radius:6px;color:#495057 !important;padding:8px;}
#uh-ts-form .row{display:flow;gap:8px;margin: 0 !important;}
#uh-ts-form .row > div{flex:1;}
#uh-ts-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:14px;}
#uh-ts-actions button{border:0;border-radius:6px;padding:8px 12px;cursor:pointer;}
#uh-ts-save{background:#f39c12;color:#1f2d3d;}
#uh-ts-cancel{background:#6c757d;color:#fff;}
#uh-ts-delete{background:#ef4444;color:white;margin-right:auto;}
#uh-ts-error{color:#f87171;font-size:12px;min-height:14px;margin-top:6px;}
      `;
      document.head.appendChild(style);

      const modal = document.createElement("div");
      modal.id = "uh-ts-modal";
      modal.innerHTML = `
  <div id="uh-ts-card" role="dialog" aria-modal="true">
    <h3 id="uh-ts-title">${i18n.titleNew}</h3>
    <form id="uh-ts-form">
      <input type="hidden" id="uh-ts-id" value="">
      <input type="hidden" id="uh-ts-date" value="">
      <label>${i18n.labelDate}</label>
      <input type="text" id="uh-ts-date-display" disabled>

      <label>${i18n.labelKind}</label>
      <select id="uh-ts-kind">
        <option>WORK</option>
        <option>LEAVE</option>
        <option>SICK</option>
        <option>OTHER</option>
      </select>

      <div class="row">
        <div>
          <label>${i18n.labelFrom}</label>
          <input type="time" id="uh-ts-from" step="300" value="09:00">
        </div>
        <div>
          <label>${i18n.labelTo}</label>
          <input type="time" id="uh-ts-to" step="300" value="17:00">
        </div>
      </div>

      <label>${i18n.labelComment}</label>
      <input type="text" id="uh-ts-comment" placeholder="">
      <div id="uh-ts-error"></div>
      <div id="uh-ts-actions">
        <button type="button" id="uh-ts-delete" style="display:none">${i18n.btnDelete}</button>
        <button type="button" id="uh-ts-cancel">${i18n.btnCancel}</button>
        <button type="submit" id="uh-ts-save">${i18n.btnSave}</button>
      </div>
    </form>
  </div>`;
      document.body.appendChild(modal);

      modal.addEventListener("click", (e) => { if (e.target.id === "uh-ts-modal") closeModal(); });
      document.getElementById("uh-ts-cancel").addEventListener("click", () => closeModal());
    }

    function openModal({ mode, dateStr, id=null, kind="WORK", minutes=0, comment="" }) {
      ensureModal();
      const m = document.getElementById("uh-ts-modal");
      const title = document.getElementById("uh-ts-title");
      const idEl = document.getElementById("uh-ts-id");
      const dateEl = document.getElementById("uh-ts-date");
      const dateDisp = document.getElementById("uh-ts-date-display");
      const kindEl = document.getElementById("uh-ts-kind");
      const fromEl = document.getElementById("uh-ts-from");
      const toEl = document.getElementById("uh-ts-to");
      const cmtEl = document.getElementById("uh-ts-comment");
      const delBtn = document.getElementById("uh-ts-delete");
      const errEl = document.getElementById("uh-ts-error");

      title.textContent = mode === "edit" ? i18n.titleEdit : i18n.titleNew;
      idEl.value = id || "";
      dateEl.value = dateStr;
      dateDisp.value = dateStr;
      kindEl.value = (kind || "WORK").toUpperCase();
      cmtEl.value = comment || "";
      errEl.textContent = "";

      if (minutes && minutes > 0) {
        const base = [9, 0];
        const end = addMinutes(base[0], base[1], minutes);
        fromEl.value = "09:00";
        toEl.value = toHHMM(end.h, end.m);
      } else {
        fromEl.value = "09:00";
        toEl.value = "17:00";
      }

      delBtn.style.display = mode === "edit" ? "" : "none";
      m.style.display = "flex";

      const form = document.getElementById("uh-ts-form");
      form.onsubmit = async (e) => {
        e.preventDefault();
        errEl.textContent = "";

        const from = fromEl.value || "00:00";
        const to = toEl.value || "00:00";
        const mins = diffMinutes(from, to);
        if (mins <= 0) { errEl.textContent = i18n.errTimeOrder; return; }

        const payload = {
          date: dateStr,
          kind: kindEl.value.trim().toUpperCase(),
          minutes: mins,
          comment: cmtEl.value || ""
        };

        try {
          if (mode === "edit") {
            const resp = await fetch(`${updateBase}${id}/`, {
              method: "PATCH",
              credentials: "same-origin",
              headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
              body: JSON.stringify({ kind: payload.kind, minutes: payload.minutes, comment: payload.comment })
            });
            if (!resp.ok) throw new Error(await resp.text() || "Update failed.");
          } else {
            const resp = await fetch(createUrl, {
              method: "POST",
              credentials: "same-origin",
              headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
              body: JSON.stringify(payload)
            });
            if (!resp.ok) throw new Error(await resp.text() || "Create failed.");
          }
          window.cal.refetchEvents();
          refreshTotals();
          closeModal();
        } catch (err) {
          errEl.textContent = (err && err.message) ? err.message : "Request failed.";
        }
      };

      document.getElementById("uh-ts-delete").onclick = async () => {
        errEl.textContent = "";
        if (!confirm(i18n.confirmDelete)) return;
        try {
          const resp = await fetch(`${deleteBase}${id}/`, {
            method: "DELETE",
            credentials: "same-origin",
            headers: { "X-CSRFToken": csrf }
          });
          if (!resp.ok) throw new Error(await resp.text() || "Delete failed.");
          window.cal.refetchEvents();
          refreshTotals();
          closeModal();
        } catch (err) {
          errEl.textContent = (err && err.message) ? err.message : "Delete failed.";
        }
      };
    }

    function closeModal() {
      const m = document.getElementById("uh-ts-modal");
      if (m) m.style.display = "none";
    }

    function toHHMM(h, m) {
      const hh = String(h).padStart(2, "0");
      const mm = String(m).padStart(2, "0");
      return `${hh}:${mm}`;
    }
    function parseHHMM(s) {
      const m = /^(\d{1,2}):(\d{2})$/.exec(s || "");
      if (!m) return { h: 0, m: 0 };
      let h = Math.min(23, Math.max(0, parseInt(m[1], 10) || 0));
      let mm = Math.min(59, Math.max(0, parseInt(m[2], 10) || 0));
      return { h, m: mm };
    }
    function diffMinutes(from, to) {
      const a = parseHHMM(from), b = parseHHMM(to);
      const start = a.h * 60 + a.m;
      const end = b.h * 60 + b.m;
      return end - start;
    }
    function addMinutes(h, m, plus) {
      let total = h * 60 + m + plus;
      if (total > 23 * 60 + 59) total = 23 * 60 + 59;
      return { h: Math.floor(total / 60), m: total % 60 };
    }

    /* ---------- Calendar ---------- */
    function run() {
      if (!window.FullCalendar) return;

      window.cal = new FullCalendar.Calendar(el, {
        initialView: "dayGridMonth",
        initialDate: initial,
        firstDay: 1,
        height: height,
        expandRows: true,
        fixedWeekCount: false,
        showNonCurrentDates: false,
        validRange: { start: initial, end: endExclusive.toISOString().slice(0, 10) },
        headerToolbar: { left: "", center: "title", right: "" },
        selectable: false,

        events: function (fetchInfo, success, failure) {
          fetch(eventsUrl, { credentials: "same-origin" })
            .then(r => r.json()).then(success).catch(failure);
        },

        dateClick: function (info) {
          openModal({ mode: "create", dateStr: info.dateStr });
        },

        eventClick: function (arg) {
          const ev = arg.event;
          const ep = ev.extendedProps || {};
          openModal({
            mode: "edit",
            dateStr: ev.startStr.slice(0, 10),
            id: ev.id,
            kind: ep.kind || "WORK",
            minutes: ep.minutes || 0,
            comment: ep.comment || ""
          });
        }
      });

      window.cal.render();
    }

    loadCSS(cssCandidates, function () { loadJS(jsCandidates, function () { run(); }); });
  }

  /* =========================
   * INIT
   * ========================= */
  function init() {
    if (!inAdminHelpPage()) injectFab();
    installUnsavedGuard();
    initCalendar();
  }
  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", init); }
  else { init(); }
})();
