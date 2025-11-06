(function () {
  "use strict";

  /* =========================
   * UNSAVED CHANGES GUARD
   * ========================= */
  function installUnsavedGuard() {
    if (window.__UH_GUARD_INSTALLED__) return;
    window.__UH_GUARD_INSTALLED__ = true;

    let dirty = false;
    const markDirty = () => { dirty = true; };

    // Track form changes
    document.addEventListener("input", markDirty, true);
    document.addEventListener("change", markDirty, true);
    
    // Clear dirty flag on successful submit
    document.addEventListener("submit", (e) => { 
      if (e.target && e.target.closest("form")) dirty = false; 
    }, true);

    // Warn on navigation clicks
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
        if (!ok) { 
          e.preventDefault(); 
          e.stopImmediatePropagation(); 
          return; 
        }
        dirty = false;
      }
    }, true);

    // Warn on browser back/refresh
    window.addEventListener("beforeunload", function (e) {
      if (!dirty) return;
      e.preventDefault();
      e.returnValue = "";
    });

    // Utility to manually clear the guard (if needed)
    window.UH_CLEAR_UNSAVED_GUARD = () => { dirty = false; };
  }

  /* =========================
   * INIT
   * ========================= */
  function init() {
    installUnsavedGuard();
  }
  
  if (document.readyState === "loading") { 
    document.addEventListener("DOMContentLoaded", init); 
  } else { 
    init(); 
  }
})();