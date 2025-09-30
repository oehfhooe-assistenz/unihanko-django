(function () {
  // Only run on change/add forms
  var form = document.querySelector("form#content-main form, form#changelist-form") 
             || document.querySelector("form");
  if (!form) return;

  var dirty = false;

  // mark dirty on any change/input
  form.addEventListener("change", function () { dirty = true; }, true);
  form.addEventListener("input",  function () { dirty = true; }, true);

  // submitting the form means "we meant to leave"
  form.addEventListener("submit", function () { dirty = false; }, true);

  // object action forms (DOA) are also forms → covered by submit above
  // If you have plain links that POST via JS, you can clear dirty on click:
  document.addEventListener("click", function (e) {
    var t = e.target.closest("button, a");
    if (!t) return;
    if (t.type === "submit" || t.getAttribute("form")) dirty = false;
  }, true);

  window.addEventListener("beforeunload", function (e) {
    if (!dirty) return;
    e.preventDefault();
    e.returnValue = ""; // required by browsers; custom text is ignored
  });
})();