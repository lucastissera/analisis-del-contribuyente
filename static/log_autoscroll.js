/** Auto-scroll del log de proceso solo si el usuario ya estaba al final. */
(function (global) {
  "use strict";

  function shouldStickToBottom(el, threshold) {
    if (!el) return true;
    var t = threshold == null ? 48 : threshold;
    return el.scrollHeight - el.scrollTop - el.clientHeight <= t;
  }

  function updateLog(el, text, opts) {
    if (!el) return;
    opts = opts || {};
    var stick = opts.forceStick === true || shouldStickToBottom(el, opts.threshold);
    el.textContent = text;
    if (stick) {
      el.scrollTop = el.scrollHeight;
    }
  }

  global.McLogAutoscroll = {
    shouldStickToBottom: shouldStickToBottom,
    updateLog: updateLog,
  };
})(window);
