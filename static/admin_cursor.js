(function () {
  "use strict";

  var cfgEl = document.getElementById("admin-cursor-config");
  var i18nEl = document.getElementById("i18n-js");
  var cfg = cfgEl ? JSON.parse(cfgEl.textContent || "{}") : {};
  var I = i18nEl ? JSON.parse(i18nEl.textContent || "{}") : {};

  var STORAGE_KEY = "aic_cursor_agent_id";
  var mensajesEl = document.getElementById("mensajes");
  var form = document.getElementById("form-chat");
  var input = document.getElementById("input-texto");
  var btnEnviar = document.getElementById("btn-enviar");
  var btnNueva = document.getElementById("btn-nueva");
  var btnCancelar = document.getElementById("btn-cancelar");
  var estadoRun = document.getElementById("estado-run");
  var avisoConfig = document.getElementById("aviso-config");
  var avisoRepo = document.getElementById("aviso-repo");
  var linkAgente = document.getElementById("link-agente");

  var agentId = null;
  var runId = null;
  var agentUrl = null;
  var eventSource = null;
  var asistenteActual = null;
  var ocupado = false;

  function t(key, fallback) {
    return I[key] || fallback || key;
  }

  function setEstado(texto, activo) {
    if (!estadoRun) return;
    estadoRun.textContent = texto;
    estadoRun.classList.toggle("activo", !!activo);
  }

  function setOcupado(val) {
    ocupado = !!val;
    if (btnEnviar) btnEnviar.disabled = ocupado;
    if (input) input.disabled = ocupado;
    if (btnCancelar) btnCancelar.hidden = !ocupado;
  }

  function guardarAgentId(id) {
    agentId = id || null;
    try {
      if (agentId) localStorage.setItem(STORAGE_KEY, agentId);
      else localStorage.removeItem(STORAGE_KEY);
    } catch (e) {}
  }

  function cargarAgentId() {
    try {
      return localStorage.getItem(STORAGE_KEY) || null;
    } catch (e) {
      return null;
    }
  }

  function actualizarLinkAgente() {
    if (!linkAgente) return;
    if (agentUrl) {
      linkAgente.href = agentUrl;
      linkAgente.hidden = false;
    } else {
      linkAgente.hidden = true;
    }
  }

  function agregarMensaje(tipo, texto, meta) {
    if (!mensajesEl || !texto) return null;
    var div = document.createElement("div");
    div.className = "msg msg-" + tipo;
    if (meta) {
      var m = document.createElement("div");
      m.className = "msg-meta";
      m.textContent = meta;
      div.appendChild(m);
    }
    var body = document.createElement("div");
    body.textContent = texto;
    div.appendChild(body);
    mensajesEl.appendChild(div);
    mensajesEl.scrollTop = mensajesEl.scrollHeight;
    return body;
  }

  function agregarTool(nombre, detalle) {
    agregarMensaje("tool", detalle, nombre || "tool");
  }

  function cerrarStream() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  function finalizarRun(estadoTexto) {
    cerrarStream();
    setOcupado(false);
    asistenteActual = null;
    setEstado(estadoTexto || t("admin_cursor_estado_listo", "Listo"), false);
  }

  function manejarEvento(tipo, data) {
    if (tipo === "assistant" && data && data.text) {
      if (!asistenteActual) {
        asistenteActual = agregarMensaje(
          "asistente",
          "",
          t("admin_cursor_asistente", "Cursor Cloud")
        );
      }
      if (asistenteActual) asistenteActual.textContent += data.text;
      if (mensajesEl) mensajesEl.scrollTop = mensajesEl.scrollHeight;
      return;
    }
    if (tipo === "status" && data && data.status) {
      setEstado(
        t("admin_cursor_estado_run", "Ejecutando") + ": " + data.status,
        true
      );
      return;
    }
    if (tipo === "tool_call" && data) {
      var det = data.name || "tool";
      if (data.status) det += " — " + data.status;
      if (data.args && data.args.path) det += " (" + data.args.path + ")";
      agregarTool(data.name, det);
      return;
    }
    if (tipo === "result" && data) {
      if (data.text && !asistenteActual) {
        asistenteActual = agregarMensaje(
          "asistente",
          data.text,
          t("admin_cursor_asistente", "Cursor Cloud")
        );
      } else if (data.text && asistenteActual && !asistenteActual.textContent) {
        asistenteActual.textContent = data.text;
      }
      var fin = data.status || "FINISHED";
      if (data.git && data.git.branches && data.git.branches.length) {
        data.git.branches.forEach(function (b) {
          var line = (b.branch || "") + (b.prUrl ? " → " + b.prUrl : "");
          if (line) agregarMensaje("sistema", line);
        });
      }
      finalizarRun(t("admin_cursor_estado_fin", "Finalizado") + ": " + fin);
      return;
    }
    if (tipo === "error") {
      agregarMensaje(
        "sistema",
        (data && data.message) || t("admin_cursor_err_stream", "Error en el stream")
      );
      finalizarRun(t("admin_cursor_estado_error", "Error"));
      return;
    }
    if (tipo === "done") {
      finalizarRun(t("admin_cursor_estado_listo", "Listo"));
    }
  }

  function parseSseChunk(texto) {
    var evento = "message";
    var datos = "";
    texto.split("\n").forEach(function (linea) {
      if (linea.indexOf("event:") === 0) evento = linea.slice(6).trim();
      if (linea.indexOf("data:") === 0) datos += linea.slice(5).trim();
    });
    if (!datos) return;
    try {
      manejarEvento(evento, JSON.parse(datos));
    } catch (e) {
      manejarEvento(evento, { text: datos });
    }
  }

  function abrirStream(aid, rid) {
    cerrarStream();
    setOcupado(true);
    setEstado(t("admin_cursor_estado_run", "Ejecutando") + "…", true);
    asistenteActual = null;

    var url =
      "/admin/cursor/stream/" +
      encodeURIComponent(aid) +
      "/" +
      encodeURIComponent(rid);
    eventSource = new EventSource(url);

    eventSource.addEventListener("assistant", function (ev) {
      parseSseChunk("event: assistant\ndata: " + ev.data);
    });
    eventSource.addEventListener("status", function (ev) {
      parseSseChunk("event: status\ndata: " + ev.data);
    });
    eventSource.addEventListener("tool_call", function (ev) {
      parseSseChunk("event: tool_call\ndata: " + ev.data);
    });
    eventSource.addEventListener("result", function (ev) {
      parseSseChunk("event: result\ndata: " + ev.data);
    });
    eventSource.addEventListener("error", function (ev) {
      if (ev.data) parseSseChunk("event: error\ndata: " + ev.data);
    });
    eventSource.addEventListener("done", function () {
      finalizarRun(t("admin_cursor_estado_listo", "Listo"));
    });
    eventSource.onerror = function () {
      if (!ocupado) return;
      agregarMensaje(
        "sistema",
        t("admin_cursor_err_conexion", "Se perdió la conexión con el agente.")
      );
      finalizarRun(t("admin_cursor_estado_error", "Error"));
    };
  }

  function enviarMensaje(texto) {
    if (!cfg.configured) {
      agregarMensaje(
        "sistema",
        t("admin_cursor_err_no_config", "Falta configurar CURSOR_API_KEY en el servidor.")
      );
      return;
    }
    agregarMensaje("usuario", texto, t("admin_cursor_vos", "Vos"));
    setOcupado(true);

    fetch("/admin/cursor/mensaje", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: texto,
        agent_id: agentId,
      }),
    })
      .then(function (r) {
        return r.json().then(function (body) {
          if (!r.ok) throw new Error((body && body.error) || r.statusText);
          return body;
        });
      })
      .then(function (body) {
        agentId = body.agent_id || agentId;
        runId = body.run_id;
        agentUrl = body.agent_url || agentUrl;
        guardarAgentId(agentId);
        actualizarLinkAgente();
        if (agentId && runId) abrirStream(agentId, runId);
        else {
          setOcupado(false);
          agregarMensaje(
            "sistema",
            t("admin_cursor_err_sin_run", "No se recibió un run válido.")
          );
        }
      })
      .catch(function (err) {
        setOcupado(false);
        agregarMensaje("sistema", String(err.message || err));
        setEstado(t("admin_cursor_estado_error", "Error"), false);
      });
  }

  function nuevaConversacion() {
    cerrarStream();
    agentId = null;
    runId = null;
    agentUrl = null;
    guardarAgentId(null);
    actualizarLinkAgente();
    setOcupado(false);
    setEstado(t("admin_cursor_estado_listo", "Listo"), false);
    if (mensajesEl) {
      mensajesEl.innerHTML = "";
      agregarMensaje("sistema", t("admin_cursor_nueva_ok", "Nueva conversación."));
    }
  }

  function cancelarRun() {
    if (!agentId || !runId) return;
    fetch(
      "/admin/cursor/cancelar/" +
        encodeURIComponent(agentId) +
        "/" +
        encodeURIComponent(runId),
      { method: "POST" }
    ).finally(function () {
      agregarMensaje("sistema", t("admin_cursor_cancelado", "Ejecución cancelada."));
      finalizarRun(t("admin_cursor_estado_cancelado", "Cancelado"));
    });
  }

  function initAvisos() {
    if (!cfg.configured && avisoConfig) {
      avisoConfig.hidden = false;
      avisoConfig.textContent = t(
        "admin_cursor_aviso_no_config",
        "Configurá CURSOR_API_KEY en Render para habilitar el chat."
      );
    }
    if (cfg.repo_url && avisoRepo) {
      avisoRepo.hidden = false;
      avisoRepo.textContent = t(
        "admin_cursor_repo",
        "Repositorio"
      ) + ": " + cfg.repo_url + " (" + (cfg.branch || "main") + ")";
    } else if (avisoRepo) {
      avisoRepo.hidden = false;
      avisoRepo.textContent = t(
        "admin_cursor_sin_repo",
        "Sin repo GitHub: el agente trabajará sin clonar código (solo chat)."
      );
    }
  }

  if (form) {
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (ocupado) return;
      var texto = (input && input.value || "").trim();
      if (!texto) return;
      if (input) input.value = "";
      enviarMensaje(texto);
    });
  }
  if (btnNueva) btnNueva.addEventListener("click", nuevaConversacion);
  if (btnCancelar) btnCancelar.addEventListener("click", cancelarRun);

  agentId = cargarAgentId();
  initAvisos();
  setEstado(t("admin_cursor_estado_listo", "Listo"), false);
})();
