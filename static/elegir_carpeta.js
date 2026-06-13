/** Diálogo nativo de carpeta vía GET /elegir-carpeta (app de escritorio). */
(function (global) {
  function elegirCarpeta(titulo) {
    var q = encodeURIComponent(titulo || "Elegir carpeta de descarga");
    return fetch("/elegir-carpeta?titulo=" + q, { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("picker_http");
        return r.json();
      })
      .then(function (data) {
        if (data && data.error) throw new Error(data.error);
        if (!data || !data.carpeta) return null;
        return data.carpeta;
      });
  }

  function enlazar(opts) {
    var input = document.getElementById(opts.inputId);
    var label = opts.labelId ? document.getElementById(opts.labelId) : null;
    var btn = opts.btnId ? document.getElementById(opts.btnId) : null;
    var titulo = opts.titulo || "Elegir carpeta de descarga";

    function aplicar(ruta) {
      if (input) input.value = ruta;
      if (label) label.textContent = ruta;
    }

    function picker() {
      if (btn) btn.disabled = true;
      return elegirCarpeta(titulo)
        .then(function (ruta) {
          if (btn) btn.disabled = false;
          if (!ruta) {
            if (opts.onCancel) opts.onCancel();
            return null;
          }
          aplicar(ruta);
          if (opts.onOk) opts.onOk(ruta);
          return ruta;
        })
        .catch(function (err) {
          if (btn) btn.disabled = false;
          if (opts.onError) opts.onError(err);
          throw err;
        });
    }

    if (btn) {
      btn.addEventListener("click", function () {
        picker().catch(function () {});
      });
    }

    return {
      elegir: picker,
      obtener: function () {
        return ((input && input.value) || "").trim();
      },
      aplicar: aplicar,
    };
  }

  function resolverCarpeta(opts) {
    var api = opts.api;
    var actual = api.obtener();
    if (actual) return Promise.resolve(actual);
    return api.elegir();
  }

  global.McElegirCarpeta = {
    elegir: elegirCarpeta,
    enlazar: enlazar,
    resolver: resolverCarpeta,
  };
})(window);
