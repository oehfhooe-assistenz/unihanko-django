(function() {
    "use strict";

    /* =========================
     * HELP FAB + OVERLAY
     * ========================= */

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

        // close actions
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
            .then((r) => r.text())
            .then((html) => {
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
        if (inAdminHelpPage()) return; // hide FAB on help pages
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

    /* =========================
     * UNSAVED CHANGES GUARD — improved
     * ========================= */
    (function() {
        var dirty = false;

        function markDirty() {
            dirty = true;
        }

        // mark dirty on any input/change anywhere in the document
        document.addEventListener("input", markDirty, true);
        document.addEventListener("change", markDirty, true);

        // submitting any form clears the guard
        document.addEventListener("submit", function(e) {
            if (e.target && e.target.closest("form")) dirty = false;
        }, true);

        // Intercept internal navigation (incl. Jazzmin sidebar links)
        document.addEventListener("click", function(e) {
            var a = e.target && e.target.closest("a[href]");
            if (!a) return;

            var href = a.getAttribute("href");
            if (!href) return;
            if (href.startsWith("#") || href.startsWith("javascript:")) return; // not real nav
            if ((a.target || "").toLowerCase() === "_blank") return; // new tab

            // same-origin check
            var url = new URL(href, location.href);
            if (url.origin !== location.origin) return;

            // allow opting out per-link
            if (a.hasAttribute("data-no-guard")) return;

            if (dirty) {
                var ok = confirm("You have unsaved changes. Leave this page?");
                if (!ok) {
                    e.preventDefault();
                    e.stopImmediatePropagation();
                    return;
                }
                dirty = false; // allow navigation
            }
        }, true);

        // Fallback for non-click navigations (address bar, refresh, etc.)
        window.addEventListener("beforeunload", function(e) {
            if (!dirty) return;
            e.preventDefault();
            e.returnValue = "";
        });

        // Optional: clear programmatically when you know you saved via AJAX, etc.
        window.UH_CLEAR_UNSAVED_GUARD = function() {
            dirty = false;
        };
    })();

    /* =========================
     * INIT
     * ========================= */

    function init() {
        if (!inAdminHelpPage()) injectFab();
        installUnsavedGuard();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();