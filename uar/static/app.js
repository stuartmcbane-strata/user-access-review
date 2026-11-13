(function () {
  function showTab(key) {
    var tabs = document.querySelectorAll("section.tab");
    if (!tabs.length) return;
    var found = false;
    tabs.forEach(function (t) { if (t.id === key) found = true; });
    if (!found) key = tabs[0].id;
    tabs.forEach(function (t) { t.classList.toggle("hidden", t.id !== key); });
    document.querySelectorAll(".tile[data-tab]").forEach(function (a) {
      a.classList.toggle("selected", a.getAttribute("data-tab") === key);
    });
  }
  document.addEventListener("DOMContentLoaded", function () {
    showTab(location.hash.slice(1));
    window.addEventListener("hashchange", function () { showTab(location.hash.slice(1)); });

    document.querySelectorAll("input[data-filter-for]").forEach(function (input) {
      input.addEventListener("input", function () {
        var target = document.getElementById(input.getAttribute("data-filter-for"));
        if (!target) return;
        var table = target.tagName === "TABLE" ? target : target.querySelector("table");
        var q = input.value.trim().toLowerCase();
        table.querySelectorAll("tbody tr:not(.empty)").forEach(function (tr) {
          tr.classList.toggle("hidden", q !== "" && tr.textContent.toLowerCase().indexOf(q) === -1);
        });
      });
    });

    document.querySelectorAll("form[data-confirm]").forEach(function (f) {
      f.addEventListener("submit", function (e) {
        if (!window.confirm(f.getAttribute("data-confirm"))) e.preventDefault();
      });
    });

    document.querySelectorAll("table.grid thead th").forEach(function (th, i) {
      th.addEventListener("click", function () {
        var table = th.closest("table");
        var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
        var rows = Array.prototype.slice.call(table.querySelectorAll("tbody tr:not(.empty)"));
        var asc = th.getAttribute("data-sort") !== "asc";
        table.querySelectorAll("thead th").forEach(function (h) { h.removeAttribute("data-sort"); });
        th.setAttribute("data-sort", asc ? "asc" : "desc");
        rows.sort(function (a, b) {
          var x = (a.children[idx] || {}).textContent || "", y = (b.children[idx] || {}).textContent || "";
          return (asc ? 1 : -1) * x.trim().localeCompare(y.trim(), undefined, { numeric: true, sensitivity: "base" });
        });
        var body = table.querySelector("tbody");
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  });
})();
