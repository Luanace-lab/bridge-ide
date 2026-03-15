onconnect = function (event) {
  var port = event.ports[0];
  var nav = self.navigator || {};
  port.onmessage = function () {
    port.postMessage({
      type: "shared-worker-result",
      scope: "shared-worker",
      navigator: {
        userAgent: nav.userAgent || null,
        platform: nav.platform || null,
        language: nav.language || null,
        languages: Array.isArray(nav.languages) ? nav.languages.slice() : null,
        webdriver: typeof nav.webdriver === "undefined" ? null : nav.webdriver,
        hasUserAgentData: typeof nav.userAgentData !== "undefined",
        hardwareConcurrency: typeof nav.hardwareConcurrency === "undefined" ? null : nav.hardwareConcurrency,
        deviceMemory: typeof nav.deviceMemory === "undefined" ? null : nav.deviceMemory
      },
      timezone: (function () {
        try {
          return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
        } catch (err) {
          return null;
        }
      }())
    });
  };
  port.start();
};
