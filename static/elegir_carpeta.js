/** Carpeta de destino: diálogo nativo (.exe) o File System Access API (web). */
(function (global) {
  var PREFIJOS_SISTEMA = {
    mis_comprobantes: "Mis Comprobantes",
    dfe: "DFE",
    nuestra_parte: "Nuestra Parte",
    analisis_programado: "Análisis Programado",
  };

  var IDB_DB = "aic-carpeta-web";
  var IDB_VER = 1;

  var _dirHandle = null;
  var _dirNombre = "";
  var _parentHandle = null;
  var _parentNombre = "";
  var _subcarpetaSesion = null;
  var _sistemaActual = null;

  function esModoEscritorio() {
    return global.MC_MODO_ESCRITORIO === true;
  }

  function soporteCarpetaWeb() {
    return typeof global.showDirectoryPicker === "function";
  }

  function requiereCarpeta(ruta) {
    if (esModoEscritorio()) {
      return !String(ruta || "").trim();
    }
    return !_dirHandle;
  }

  function obtenerHandleWeb() {
    return _dirHandle;
  }

  function obtenerNombreWeb() {
    return _dirNombre;
  }

  function obtenerSubcarpetaSesion() {
    return _subcarpetaSesion;
  }

  function stampCarpetaEjecucion(fecha) {
    var d = fecha || new Date();
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    var h = String(d.getHours()).padStart(2, "0");
    var min = String(d.getMinutes()).padStart(2, "0");
    return y + "-" + m + "-" + day + " " + h + "-" + min;
  }

  function nombreSubcarpetaSistema(sistema) {
    var pref = PREFIJOS_SISTEMA[sistema];
    if (!pref) return null;
    return pref + " " + stampCarpetaEjecucion();
  }

  function abrirIdb() {
    return new Promise(function (resolve, reject) {
      if (!global.indexedDB) {
        reject(new Error("no_idb"));
        return;
      }
      var req = global.indexedDB.open(IDB_DB, IDB_VER);
      req.onerror = function () {
        reject(req.error);
      };
      req.onupgradeneeded = function (ev) {
        ev.target.result.createObjectStore("handles", { keyPath: "sistema" });
      };
      req.onsuccess = function () {
        resolve(req.result);
      };
    });
  }

  function guardarEnIdb(sistema, data) {
    return abrirIdb()
      .then(function (db) {
        return new Promise(function (resolve, reject) {
          var tx = db.transaction("handles", "readwrite");
          tx.objectStore("handles").put(
            Object.assign({ sistema: sistema }, data)
          );
          tx.oncomplete = function () {
            resolve();
          };
          tx.onerror = function () {
            reject(tx.error);
          };
        });
      })
      .catch(function () {});
  }

  function leerDeIdb(sistema) {
    return abrirIdb()
      .then(function (db) {
        return new Promise(function (resolve, reject) {
          var tx = db.transaction("handles", "readonly");
          var req = tx.objectStore("handles").get(sistema);
          req.onsuccess = function () {
            resolve(req.result || null);
          };
          req.onerror = function () {
            reject(req.error);
          };
        });
      })
      .catch(function () {
        return null;
      });
  }

  function restaurarDesdeIdb(sistema) {
    return leerDeIdb(sistema).then(function (row) {
      if (!row || !row.dirHandle) return false;
      return row.dirHandle
        .queryPermission({ mode: "readwrite" })
        .then(function (perm) {
          if (perm !== "granted") return false;
          _dirHandle = row.dirHandle;
          _subcarpetaSesion = row.subcarpetaSesion || null;
          _parentNombre = row.parentNombre || row.dirHandle.name || "";
          _dirNombre = row.dirNombre || row.dirHandle.name || "";
          _sistemaActual = sistema;
          return true;
        });
    }).catch(function () {
      return false;
    });
  }

  function esErrorCarpetaRestringida(err) {
    if (!err) return false;
    var nombre = String(err.name || "");
    var msg = String(err.message || "").toLowerCase();
    if (nombre === "SecurityError") {
      return (
        msg.indexOf("system") >= 0 ||
        msg.indexOf("sistema") >= 0 ||
        msg.indexOf("restricted") >= 0 ||
        msg.indexOf("restring") >= 0
      );
    }
    return (
      msg.indexOf("system file") >= 0 ||
      msg.indexOf("archivos del sistema") >= 0 ||
      msg.indexOf("contains system") >= 0 ||
      msg.indexOf("contiene archivos") >= 0
    );
  }

  function esPermisoDenegado(err) {
    if (!err || err.name !== "NotAllowedError") return false;
    if (esErrorCarpetaRestringida(err)) return false;
    return true;
  }

  function mensajeError(err, textos) {
    textos = textos || {};
    var cancelada =
      textos.cancelada ||
      textos.carpeta_cancelada ||
      "No se eligió ninguna carpeta.";
    var noSoportado =
      textos.noSoportado ||
      textos.err_carpeta_web_api ||
      textos.errCarpetaWebApi ||
      cancelada;
    var restringida =
      textos.restringida ||
      textos.err_carpeta_restringida ||
      textos.errCarpetaRestringida ||
      cancelada;
    var permisoDenegado =
      textos.permisoDenegado ||
      textos.err_carpeta_permiso_denegado ||
      textos.errCarpetaPermisoDenegado ||
      cancelada;

    if (!err) return cancelada;
    if (err.message === "picker_web_no_soportado") return noSoportado;
    if (err.message === "picker_permiso_denegado" || esPermisoDenegado(err)) {
      return permisoDenegado;
    }
    if (err.message === "picker_carpeta_restringida" || esErrorCarpetaRestringida(err)) {
      return restringida;
    }
    return cancelada;
  }

  function actualizarCampoSesion(sesionInputId) {
    if (!sesionInputId) return;
    var el = document.getElementById(sesionInputId);
    if (el) el.value = _subcarpetaSesion || "";
  }

  function persistirEstado(sistema) {
    if (!sistema || !_dirHandle) return Promise.resolve();
    return guardarEnIdb(sistema, {
      dirHandle: _dirHandle,
      subcarpetaSesion: _subcarpetaSesion,
      parentNombre: _parentNombre,
      dirNombre: _dirNombre,
    });
  }

  function asegurarSubcarpetaSesion(sistema, sesionInputId) {
    if (!sistema || sistema === "analisis_programado") {
      _subcarpetaSesion = null;
      actualizarCampoSesion(sesionInputId);
      return Promise.resolve(_dirNombre);
    }
    if (_subcarpetaSesion && _dirHandle) {
      actualizarCampoSesion(sesionInputId);
      return Promise.resolve(_dirNombre);
    }

    var base = _parentHandle || _dirHandle;
    if (!base) {
      return Promise.reject(new Error("picker_sin_carpeta"));
    }

    var subNombre = nombreSubcarpetaSistema(sistema);
    return base
      .getDirectoryHandle(subNombre, { create: true })
      .then(function (subHandle) {
        _parentHandle = base;
        _parentNombre = base.name || _parentNombre || "Carpeta";
        _dirHandle = subHandle;
        _subcarpetaSesion = subNombre;
        _dirNombre = _parentNombre + " / " + subNombre;
        _sistemaActual = sistema;
        actualizarCampoSesion(sesionInputId);
        return persistirEstado(sistema).then(function () {
          return _dirNombre;
        });
      })
      .catch(function (err) {
        _dirHandle = base;
        _parentHandle = base;
        _parentNombre = base.name || _parentNombre || "Carpeta";
        _subcarpetaSesion = subNombre;
        _dirNombre = _parentNombre + " / " + subNombre;
        actualizarCampoSesion(sesionInputId);
        return persistirEstado(sistema).then(function () {
          return _dirNombre;
        });
      });
  }

  function elegirCarpetaNativa(titulo) {
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

  function elegirCarpetaWeb(titulo, sistema, sesionInputId) {
    if (!soporteCarpetaWeb()) {
      return Promise.reject(new Error("picker_web_no_soportado"));
    }

    var pickerId = "aic-" + (sistema || "mis_comprobantes");

    return global
      .showDirectoryPicker({
        mode: "readwrite",
        startIn: "downloads",
        id: pickerId,
      })
      .then(function (parentHandle) {
        _parentHandle = parentHandle;
        _parentNombre = parentHandle.name || "Carpeta";
        _dirHandle = parentHandle;

        if (sistema === "analisis_programado") {
          _dirNombre = _parentNombre;
          _subcarpetaSesion = null;
          actualizarCampoSesion(sesionInputId);
          return persistirEstado(sistema).then(function () {
            return _dirNombre;
          });
        }

        return asegurarSubcarpetaSesion(sistema, sesionInputId);
      })
      .catch(function (err) {
        if (err && err.name === "AbortError") return null;
        if (esPermisoDenegado(err)) {
          throw new Error("picker_permiso_denegado");
        }
        if (esErrorCarpetaRestringida(err)) {
          throw new Error("picker_carpeta_restringida");
        }
        throw err;
      });
  }

  function elegirCarpeta(titulo, sistema, sesionInputId) {
    if (esModoEscritorio()) {
      return elegirCarpetaNativa(titulo);
    }
    return elegirCarpetaWeb(titulo, sistema, sesionInputId);
  }

  function configurarUiWeb(opts) {
    if (esModoEscritorio()) return;
    if (!soporteCarpetaWeb() && opts.onError) {
      opts.onError(new Error("picker_web_no_soportado"));
    }
  }

  function enlazar(opts) {
    var input = document.getElementById(opts.inputId);
    var label = opts.labelId ? document.getElementById(opts.labelId) : null;
    var btn = opts.btnId ? document.getElementById(opts.btnId) : null;
    var titulo = opts.titulo || "Elegir carpeta de descarga";
    var textos = opts.textos || null;
    var sistema = opts.sistema || "mis_comprobantes";
    var sesionInputId = opts.sesionInputId || null;

    configurarUiWeb(opts);

    function aplicar(ruta) {
      if (input) input.value = ruta;
      if (label) label.textContent = ruta;
      actualizarCampoSesion(sesionInputId);
    }

    if (!esModoEscritorio()) {
      restaurarDesdeIdb(sistema).then(function (ok) {
        if (ok) aplicar(_dirNombre);
      });
    }

    function picker() {
      if (btn) btn.disabled = true;
      return elegirCarpeta(titulo, sistema, sesionInputId)
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
          if (opts.onError) opts.onError(err, mensajeError(err, textos));
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
        if (esModoEscritorio()) {
          return ((input && input.value) || "").trim();
        }
        return _dirNombre || "";
      },
      aplicar: aplicar,
    };
  }

  function resolverCarpeta(opts) {
    var api = opts.api;
    var sistema = opts.sistema || _sistemaActual || "mis_comprobantes";
    var sesionInputId = opts.sesionInputId || null;

    function finalizar() {
      if (esModoEscritorio()) {
        return Promise.resolve(api.obtener());
      }
      return asegurarSubcarpetaSesion(sistema, sesionInputId).then(function () {
        api.aplicar(_dirNombre);
        return _dirNombre;
      });
    }

    if (esModoEscritorio()) {
      var actual = api.obtener();
      if (actual) return Promise.resolve(actual);
      return api.elegir();
    }
    if (_dirHandle) return finalizar();
    return api.elegir().then(function (ruta) {
      if (!ruta) return null;
      return finalizar();
    });
  }

  function limpiarCarpetaWeb() {
    _dirHandle = null;
    _dirNombre = "";
    _parentHandle = null;
    _parentNombre = "";
    _subcarpetaSesion = null;
    _sistemaActual = null;
    document.querySelectorAll('input[name="web_carpeta_sesion"]').forEach(function (el) {
      el.value = "";
    });
    if (global.indexedDB) {
      abrirIdb()
        .then(function (db) {
          return new Promise(function (resolve) {
            var tx = db.transaction("handles", "readwrite");
            tx.objectStore("handles").clear();
            tx.oncomplete = function () {
              resolve();
            };
          });
        })
        .catch(function () {});
    }
  }

  global.McElegirCarpeta = {
    elegir: elegirCarpeta,
    enlazar: enlazar,
    resolver: resolverCarpeta,
    requiereCarpeta: requiereCarpeta,
    esModoEscritorio: esModoEscritorio,
    soporteCarpetaWeb: soporteCarpetaWeb,
    obtenerHandleWeb: obtenerHandleWeb,
    obtenerSubcarpetaSesion: obtenerSubcarpetaSesion,
    limpiarCarpetaWeb: limpiarCarpetaWeb,
    mensajeError: mensajeError,
    esErrorCarpetaRestringida: esErrorCarpetaRestringida,
    nombreSubcarpetaSistema: nombreSubcarpetaSistema,
  };
})(window);
