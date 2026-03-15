self.addEventListener("message", function () {
  var nav = self.navigator || {};
  var payload = {
    type: "worker-result",
    scope: "worker",
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
  };
  self.postMessage(payload);
});
