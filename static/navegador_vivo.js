/** Toggle «ver navegador en vivo» (desactivado por defecto). */
(function () {
  function initToggle(btn) {
    var inputId = btn.getAttribute("data-input");
    if (!inputId) return;
    var input = document.getElementById(inputId);
    if (!input) return;

    function sync() {
      var on = input.value === "1";
      btn.classList.toggle("activo", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    }

    btn.addEventListener("click", function () {
      input.value = input.value === "1" ? "" : "1";
      sync();
    });
    sync();
  }

  document.querySelectorAll(".btn-toggle-navegador").forEach(initToggle);
})();
