/** Mostrar/ocultar claves fiscales en campos manuales (delegación en documento). */
(function () {
  function labelMostrar(btn) {
    return btn.getAttribute("data-label-mostrar") || "Ver";
  }
  function labelOcultar(btn) {
    return btn.getAttribute("data-label-ocultar") || "Ocultar";
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".clave-toggle");
    if (!btn) return;
    e.preventDefault();
    var wrap = btn.closest(".clave-wrap");
    if (!wrap) return;
    var inp = wrap.querySelector(".clave-input");
    if (!inp) return;
    var show = inp.type === "password";
    inp.type = show ? "text" : "password";
    if (btn.classList.contains("clave-toggle-icon")) {
      btn.classList.toggle("activo", show);
      btn.setAttribute("aria-pressed", show ? "true" : "false");
      var txt = show ? labelOcultar(btn) : labelMostrar(btn);
      btn.setAttribute("aria-label", txt);
      return;
    }
    var txt = show ? labelOcultar(btn) : labelMostrar(btn);
    btn.textContent = txt;
    btn.setAttribute("aria-label", txt);
  });

  window.resetClaveFields = function (root) {
    var scope = root || document;
    scope.querySelectorAll(".clave-wrap").forEach(function (wrap) {
      var inp = wrap.querySelector(".clave-input");
      var btn = wrap.querySelector(".clave-toggle");
      if (inp) inp.type = "password";
      if (btn) {
        btn.classList.remove("activo");
        btn.setAttribute("aria-pressed", "false");
        var ver = labelMostrar(btn);
        if (!btn.classList.contains("clave-toggle-icon")) {
          btn.textContent = ver;
        }
        btn.setAttribute("aria-label", ver);
      }
    });
  };
})();
