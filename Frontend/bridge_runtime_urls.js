(function(global){
  'use strict';

  function trimTrailingSlash(value){
    return String(value || '').replace(/\/+$/, '');
  }

  function normalizeHttpBase(raw, fallbackHref){
    return trimTrailingSlash(new URL(String(raw || ''), fallbackHref).toString());
  }

  function normalizeWsBase(raw, fallbackHref){
    const url = new URL(String(raw || ''), fallbackHref);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    return trimTrailingSlash(url.toString());
  }

  function usesLocalBridgePorts(pageUrl){
    return (
      pageUrl.hostname === '127.0.0.1'
      || pageUrl.hostname === 'localhost'
      || pageUrl.port === '8787'
      || pageUrl.port === '9111'
      || pageUrl.port === '9112'
    );
  }

  function resolveConfig(options){
    const href = String(
      (options && options.href)
      || (global.location && global.location.href)
      || 'http://127.0.0.1:9111/'
    );
    const pageUrl = new URL(href);
    const apiOverride = trimTrailingSlash((options && options.apiBase) || global.__BRIDGE_API_BASE || '');
    const wsOverride = trimTrailingSlash((options && options.wsBase) || global.__BRIDGE_WS_BASE || '');
    const httpProtocol = pageUrl.protocol === 'https:' ? 'https:' : 'http:';
    const wsProtocol = pageUrl.protocol === 'https:' ? 'wss:' : 'ws:';

    const apiBase = apiOverride
      ? normalizeHttpBase(apiOverride, href)
      : usesLocalBridgePorts(pageUrl)
        ? httpProtocol + '//' + pageUrl.hostname + ':9111'
        : trimTrailingSlash(pageUrl.origin);

    const wsUrl = wsOverride
      ? normalizeWsBase(wsOverride, href)
      : usesLocalBridgePorts(pageUrl)
        ? wsProtocol + '//' + pageUrl.hostname + ':9112'
        : wsProtocol + '//' + pageUrl.host;

    return {
      apiBase,
      wsUrl,
      apiOrigin: new URL(apiBase).origin,
      wsOrigin: new URL(wsUrl).origin,
    };
  }

  function isBridgeHttpTarget(input, apiBase, fallbackHref){
    try {
      const raw = input instanceof Request ? input.url : String(input);
      const href = fallbackHref || (global.location && global.location.href) || 'http://127.0.0.1:9111/';
      const targetUrl = new URL(raw, href);
      const targetApiBase = apiBase || resolveConfig({ href }).apiBase;
      return targetUrl.origin === new URL(targetApiBase).origin;
    } catch {
      return false;
    }
  }

  function buildWsUrl(rawUrl, wsUrl, token, fallbackHref){
    try {
      const href = fallbackHref || (global.location && global.location.href) || 'http://127.0.0.1:9111/';
      const resolvedWsUrl = wsUrl || resolveConfig({ href }).wsUrl;
      const url = new URL(String(rawUrl || resolvedWsUrl), href);
      if(token && url.origin === new URL(resolvedWsUrl).origin && !url.searchParams.has('token')){
        url.searchParams.set('token', token);
      }
      return url.toString();
    } catch {
      return rawUrl;
    }
  }

  global.BridgeRuntimeUrls = {
    resolveConfig,
    isBridgeHttpTarget,
    buildWsUrl,
  };
})(window);
