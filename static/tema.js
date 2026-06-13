(function () {
  var I18N = {};
  try {
    var el = document.getElementById("i18n-js");
    if (el && el.textContent) I18N = JSON.parse(el.textContent);
  } catch (e) {}
  var root = document.documentElement;
  var btn = document.getElementById("btn-tema");
  if (!btn) return;
  var KEY = "tema";
  var textoBtn = btn.querySelector(".btn-tema-texto");

  function sincronizarBoton(oscuro) {
    btn.setAttribute("aria-pressed", oscuro ? "true" : "false");
    if (textoBtn) {
      textoBtn.textContent = oscuro ? I18N.theme_light || "" : I18N.theme_dark || "";
    }
    btn.setAttribute(
      "aria-label",
      oscuro ? I18N.aria_theme_light || "" : I18N.aria_theme_dark || ""
    );
  }

  function aplicar(oscuro) {
    root.classList.toggle("modo-oscuro", oscuro);
    try {
      localStorage.setItem(KEY, oscuro ? "oscuro" : "claro");
    } catch (e) {}
    var fav = document.getElementById("favicon");
    if (fav) {
      fav.href = oscuro
        ? fav.getAttribute("data-icon-oscuro") || fav.href
        : fav.getAttribute("data-icon-claro") || fav.href;
    }
    sincronizarBoton(oscuro);
  }

  sincronizarBoton(root.classList.contains("modo-oscuro"));

  btn.addEventListener("click", function () {
    aplicar(!root.classList.contains("modo-oscuro"));
  });
})();
