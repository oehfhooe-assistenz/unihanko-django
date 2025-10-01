(function() {
    "use strict";

    /* ========== HELP FAB (unchanged) ========== */
    function inAdminHelpPage() {
        return location.pathname.startsWith("/admin/help/");
    }

    function getAppModelFromBody() {
        const classes = (document.body.className || "").split(/\s+/);
        let app = null,
            model = null;
        for (const c of classes) {
            if (c.startsWith("app-")) app = c.slice(4);
            if (c.startsWith("model-")) model = c.slice(6);
        }
        return {
            app,
            model
        };
    }

    function targetHelpUrl() {
        const {
            app,
            model
        } = getAppModelFromBody();
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
      </div>
    `;
        document.body.appendChild(overlay);
        overlay.addEventListener("click", (e) => {
            if (e.target.id === "uh-help-overlay") closeOverlay();
        });
        overlay.addEventListener("click", (e) => {
            if (e.target && e.target.classList.contains("uh-help-close")) closeOverlay();
        });
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") closeOverlay();
        });
    }

    function openOverlayWith(url) {
        ensureOverlay();
        const overlay = document.getElementById("uh-help-overlay");
        const body = overlay.querySelector(".uh-help-body");
        overlay.style.display = "flex";
        body.textContent = "Loading…";
        fetch(url + (url.includes("?") ? "&" : "?") + "fragment=1", {
                credentials: "same-origin"
            })
            .then(r => r.text())
            .then(html => {
                body.innerHTML = html;
            })
            .catch(() => {
                body.textContent = "Failed to load help.";
            });
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
        a.addEventListener("click", function(e) {
            e.preventDefault();
            openOverlayWith(this.href);
        });
        document.body.appendChild(a);
    }

    /* ========== UNSAVED CHANGES GUARD (unchanged) ========== */
    (function() {
        var dirty = false;

        function markDirty() {
            dirty = true;
        }
        document.addEventListener("input", markDirty, true);
        document.addEventListener("change", markDirty, true);
        document.addEventListener("submit", function(e) {
            if (e.target && e.target.closest("form")) dirty = false;
        }, true);
        document.addEventListener("click", function(e) {
            var a = e.target && e.target.closest("a[href]");
            if (!a) return;
            var href = a.getAttribute("href");
            if (!href) return;
            if (href.startsWith("#") || href.startsWith("javascript:")) return;
            if ((a.target || "").toLowerCase() === "_blank") return;
            var url = new URL(href, location.href);
            if (url.origin !== location.origin) return;
            if (a.hasAttribute("data-no-guard")) return;
            if (dirty) {
                var ok = confirm("You have unsaved changes. Leave this page?");
                if (!ok) {
                    e.preventDefault();
                    e.stopImmediatePropagation();
                    return;
                }
                dirty = false;
            }
        }, true);
        window.addEventListener("beforeunload", function(e) {
            if (!dirty) return;
            e.preventDefault();
            e.returnValue = "";
        });
        window.UH_CLEAR_UNSAVED_GUARD = function() {
            dirty = false;
        };
    })();

    /* ========== FULLCALENDAR LOADER (new) ========== */
    function loadScript(src) {
        return new Promise(function(resolve, reject) {
            if (!src) {
                resolve();
                return;
            }
            var s = document.createElement("script");
            s.src = src;
            s.async = true;
            s.onload = resolve;
            s.onerror = reject;
            document.head.appendChild(s);
        });
    }

    function loadCss(href) {
        return new Promise(function(resolve, reject) {
            if (!href) {
                resolve();
                return;
            }
            // don’t double-insert
            if ([...document.styleSheets].some(ss => ss.href && ss.href.indexOf(href) !== -1)) {
                resolve();
                return;
            }
            var l = document.createElement("link");
            l.rel = "stylesheet";
            l.href = href;
            l.onload = resolve;
            l.onerror = reject;
            document.head.appendChild(l);
        });
    }

    function initCalendar() {
        var el = document.getElementById("ts-calendar");
        if (!el) return;

        function boot() {
            if (!(window.FullCalendar && window.FullCalendar.Calendar)) return;
            var url = el.getAttribute("data-json-url");
            var initial = el.getAttribute("data-initial"); // YYYY-MM-01
            var cal = new FullCalendar.Calendar(el, {
                initialView: "dayGridMonth",
                initialDate: initial,
                firstDay: 1,
                height: "auto",
                headerToolbar: {
                    left: "",
                    center: "title",
                    right: ""
                },
                events: function(fetchInfo, success, failure) {
                    fetch(url, {
                            credentials: "same-origin"
                        })
                        .then(r => r.json())
                        .then(data => success(data))
                        .catch(failure);
                },
                dateClick: function(info) {
                    var m = location.pathname.match(/\/(\d+)\/change\/?$/);
                    if (!m) return;
                    var addUrl = "/admin/employees/timeentry/add/?timesheet=" + m[1] + "&date=" + info.dateStr;
                    window.open(addUrl, "_blank");
                }
            });
            cal.render();
        }

        // If FC already present, just boot
        if (window.FullCalendar && window.FullCalendar.Calendar) {
            boot();
            return;
        }

        // Otherwise load from data attrs (fallback to CDN)
        var jsSrc = el.getAttribute("data-fc-src") ||
            "https://cdnjs.cloudflare.com/ajax/libs/fullcalendar/6.1.19/index.min.js";
        var cssSrc = el.getAttribute("data-fc-css") || ""; // ok to be blank

        // Load CSS (non-blocking), then JS, then boot
        loadCss(cssSrc).finally(function() {
            loadScript(jsSrc).then(boot).catch(function(err) {
                // best-effort message in the container
                el.innerHTML = "<div style='color:#f87171;'>Failed to load calendar script.</div>";
                // console for debugging
                console.error("FullCalendar load error:", err);
            });
        });
    }

    /* ========== INIT ========== */
    function init() {
        if (!inAdminHelpPage()) injectFab();
        initCalendar(); // will no-op if not on a Timesheet page
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();

})();