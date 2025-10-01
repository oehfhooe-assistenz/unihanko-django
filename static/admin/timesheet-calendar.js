(function () {
  function initCalendar() {
    var el = document.getElementById("ts-calendar");
    if (!el || !window.FullCalendar) return;

    var url = el.getAttribute("data-json-url");
    var initial = el.getAttribute("data-initial"); // YYYY-MM-01

    var cal = new FullCalendar.Calendar(el, {
      initialView: "dayGridMonth",
      initialDate: initial,
      firstDay: 1,         // Monday
      height: "auto",
      headerToolbar: { left: "", center: "title", right: "" },
      events: function(fetchInfo, success, failure) {
        fetch(url, { credentials: "same-origin" })
          .then(r => r.json())
          .then(data => success(data))
          .catch(failure);
      },
      dateClick: function(info) {
        // open Add TimeEntry prefilled
        var m = location.pathname.match(/\/(\d+)\/change\/?$/);
        if (!m) return;
        var addUrl = "/admin/employees/timeentry/add/?timesheet=" + m[1] + "&date=" + info.dateStr;
        window.open(addUrl, "_blank");
      }
    });

    cal.render();
  }

  if (document.readyState !== "loading") initCalendar();
  else document.addEventListener("DOMContentLoaded", initCalendar);
})();
