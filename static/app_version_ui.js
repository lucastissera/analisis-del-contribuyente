(function () {
  var btn = document.getElementById("btn-changelog-version");
  var dlg = document.getElementById("modal-changelog");
  var lista = document.getElementById("modal-changelog-lista");
  if (!btn || !dlg || !lista) return;

  var tplUltima = btn.getAttribute("data-tpl-ultima") || "";
  var tplDisp = btn.getAttribute("data-tpl-disponible") || "";
  var tplSinRed = btn.getAttribute("data-tpl-sin-red") || "";
  var releases = [];

  function pintarChangelog() {
    lista.innerHTML = "";
    (releases || []).forEach(function (rel) {
      var art = document.createElement("article");
      var h = document.createElement("h3");
      var ver = (rel && rel.version) || "";
      var fecha = (rel && rel.fecha) || "";
      h.textContent = fecha ? ver + " — " + fecha : ver;
      art.appendChild(h);
      var ul = document.createElement("ul");
      var cambios = (rel && rel.cambios) || [];
      cambios.forEach(function (c) {
        var li = document.createElement("li");
        li.textContent = c;
        ul.appendChild(li);
      });
      art.appendChild(ul);
      lista.appendChild(art);
    });
  }

  function abrir() {
    pintarChangelog();
    if (typeof dlg.showModal === "function") dlg.showModal();
    else dlg.setAttribute("open", "");
  }

  btn.addEventListener("click", abrir);

  fetch("/api/app-version", { credentials: "same-origin" })
    .then(function (r) {
      return r.json();
    })
    .then(function (data) {
      if (!data || !data.ok) return;
      releases = data.releases || [];
      if (!data.es_ultima) {
        var v = data.latest || "";
        btn.textContent = tplDisp.replace("__V__", v);
        btn.classList.add("barra-version-estado-nueva");
        return;
      }
      btn.classList.remove("barra-version-estado-nueva");
      btn.textContent = data.comprobado === false && tplSinRed ? tplSinRed : tplUltima;
    })
    .catch(function () {
      if (tplSinRed) btn.textContent = tplSinRed;
    });
})();
