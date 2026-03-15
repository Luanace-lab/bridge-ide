/* buddy_widget.js — Freischwebendes Buddy Chat-Widget
   Standalone, keine Abhaengigkeiten. Einbinden: <script src="buddy_widget.js"></script> vor </body>
   Theme-aware: liest CSS Custom Properties (--bgFlat, --sidebar, --sbDark) direkt von der Seite */
(function(){
  'use strict';
  const BUDDY_WIDGET_CONFIG = {
    autoOpenOnInit: true,
    openOnIncoming: true,
    mountSelector: null,
    cloudMode: false,
    storageNamespace: '',
    defaultPosition: null,
    ...((window && window.BRIDGE_BUDDY_WIDGET_CONFIG) || {})
  };
  const BUDDY_RUNTIME_FALLBACK = (function(){
    const pageUrl = new URL(window.location.href);
    const httpProtocol = pageUrl.protocol === 'https:' ? 'https:' : 'http:';
    const wsProtocol = pageUrl.protocol === 'https:' ? 'wss:' : 'ws:';
    const useLocalBridgePorts = (
      pageUrl.hostname === '127.0.0.1'
      || pageUrl.hostname === 'localhost'
      || pageUrl.port === '8787'
      || pageUrl.port === '9111'
      || pageUrl.port === '9112'
    );
    return {
      apiBase: useLocalBridgePorts ? httpProtocol + '//' + pageUrl.hostname + ':9111' : pageUrl.origin,
      wsUrl: useLocalBridgePorts ? wsProtocol + '//' + pageUrl.hostname + ':9112' : wsProtocol + '//' + pageUrl.host,
    };
  })();
  const BRIDGE_RUNTIME = window.BridgeRuntimeUrls
    ? window.BridgeRuntimeUrls.resolveConfig()
    : BUDDY_RUNTIME_FALLBACK;
  const API = BRIDGE_RUNTIME.apiBase;
  const WS_URL = BRIDGE_RUNTIME.wsUrl;
  const BRIDGE_UI_TOKEN = typeof window.__BRIDGE_UI_TOKEN === 'string' ? window.__BRIDGE_UI_TOKEN : '';
  const STORAGE_PREFIX = BUDDY_WIDGET_CONFIG.storageNamespace ? String(BUDDY_WIDGET_CONFIG.storageNamespace) + ':' : '';
  const POS_KEY = STORAGE_PREFIX + 'buddyWidgetPos';
  const BUBBLE_POS_KEY = STORAGE_PREFIX + 'buddyWidgetBubblePos';
  const BUBBLE_SIZE_KEY = STORAGE_PREFIX + 'buddyWidgetBubbleSize';
  const SEEN_KEY = STORAGE_PREFIX + 'buddyWidgetFirstSeen';
  const mountRoot = (() => {
    const selector = BUDDY_WIDGET_CONFIG.mountSelector;
    if(!selector) return document.body;
    return document.querySelector(selector) || document.body;
  })();
  const widgetDefaultPosition = (BUDDY_WIDGET_CONFIG.defaultPosition && typeof BUDDY_WIDGET_CONFIG.defaultPosition === 'object')
    ? BUDDY_WIDGET_CONFIG.defaultPosition
    : {};
  const mountedInSurface = mountRoot !== document.body;
  const cloudMode = !!BUDDY_WIDGET_CONFIG.cloudMode;

  function isBridgeHttpTarget(input){
    try {
      const raw = typeof input === 'string' ? input : (input && typeof input.url === 'string' ? input.url : '');
      const url = new URL(raw, window.location.href);
      if(window.BridgeRuntimeUrls){
        return window.BridgeRuntimeUrls.isBridgeHttpTarget(url.toString(), API, window.location.href);
      }
      return url.origin === new URL(API).origin;
    } catch {
      return false;
    }
  }

  function buddyAuthHeaders(initHeaders){
    const merged = new Headers(initHeaders || {});
    if(BRIDGE_UI_TOKEN && !merged.has('X-Bridge-Token')){
      merged.set('X-Bridge-Token', BRIDGE_UI_TOKEN);
    }
    return merged;
  }

  function bridgeFetch(input, init){
    if(!BRIDGE_UI_TOKEN || !isBridgeHttpTarget(input)){
      return fetch(input, init);
    }
    const reqInit = {...(init || {})};
    reqInit.headers = buddyAuthHeaders(reqInit.headers);
    return fetch(input, reqInit);
  }

  function buildBridgeWsUrl(rawUrl){
    try {
      if(window.BridgeRuntimeUrls){
        return window.BridgeRuntimeUrls.buildWsUrl(rawUrl, WS_URL, BRIDGE_UI_TOKEN, window.location.href);
      }
      const url = new URL(rawUrl, window.location.href);
      if(BRIDGE_UI_TOKEN && url.origin === new URL(WS_URL).origin && !url.searchParams.has('token')){
        url.searchParams.set('token', BRIDGE_UI_TOKEN);
      }
      return url.toString();
    } catch {
      return rawUrl;
    }
  }

  /* ========== Theme Colors — aus CSS Custom Properties ==========
     Themes definiert in chat.html / control_center.html:
     warm:  --bgFlat:#fbf8f1  --sidebar:#c8bfa8  --sbDark:#8a7f6a
     light: --bgFlat:#ffffff  --sidebar:#d6e8f7  --sbDark:#5a9ac7
     rose:  --bgFlat:#fdf2f4  --sidebar:#e8c4cc  --sbDark:#a3707e
     dark:  --bgFlat:#161e3a  --sidebar:#1e2a42  --sbDark:#8aa4c8
     black: --bgFlat:#000000  --sidebar:#111111  --sbDark:#7a8fa8 */
  function getThemeColors(){
    const cs = getComputedStyle(document.documentElement);
    const theme = document.documentElement.getAttribute('data-theme') || 'warm';
    const isDark = theme === 'dark' || theme === 'black';
    const bgFlat = cs.getPropertyValue('--bgFlat').trim() || (isDark ? '#161e3a' : '#fbf8f1');
    const sidebar = cs.getPropertyValue('--sidebar').trim() || (isDark ? '#1e2a42' : '#c8bfa8');
    const sbDark = cs.getPropertyValue('--sbDark').trim() || (isDark ? '#8aa4c8' : '#8a7f6a');
    return {
      bg: bgFlat,
      border: isDark ? 'rgba(255,255,255,.10)' : 'color-mix(in srgb, ' + sidebar + ' 25%, transparent)',
      text: isDark ? '#e7edf5' : sbDark,
      textMuted: isDark ? '#6b7a8f' : 'color-mix(in srgb, ' + sbDark + ' 60%, transparent)',
      bubbleBg: isDark ? 'rgba(255,255,255,.03)' : 'color-mix(in srgb, ' + sidebar + ' 8%, ' + bgFlat + ')',
      /* Message BGs identisch zu chat.html Management Board */
      userBg: isDark ? 'color-mix(in srgb, ' + sidebar + ' 25%, transparent)' : 'color-mix(in srgb, ' + sidebar + ' 25%, transparent)',
      userBorder: isDark ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.06)',
      userShadow: isDark ? 'inset 0 2px 4px rgba(255,255,255,.08), 0 1px 3px rgba(0,0,0,.12)' : '0 1px 3px rgba(0,0,0,.06)',
      buddyBg: isDark ? 'rgba(255,255,255,.08)' : 'rgba(255,255,255,.7)',
      buddyBorder: isDark ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.06)',
      buddyShadow: isDark ? 'inset 0 2px 4px rgba(255,255,255,.08), 0 1px 3px rgba(0,0,0,.12)' : '0 1px 3px rgba(0,0,0,.06)',
      accent: '#22c55e',
      iconBg: isDark ? '#1e2a42' : bgFlat,
      iconBorder: isDark ? 'rgba(255,255,255,.12)' : 'color-mix(in srgb, ' + sidebar + ' 40%, transparent)',
      shadow: isDark ? 'rgba(0,0,0,.5)' : 'rgba(0,0,0,.12)',
      /* Header bg matches chat.html boardHeader: sidebar 15% tint */
      headerBg: isDark ? 'rgba(255,255,255,.04)' : 'color-mix(in srgb, ' + sidebar + ' 15%, transparent)',
      /* Messages area: white for light themes, dark bg for dark */
      messagesBg: isDark ? 'rgba(0,0,0,.15)' : '#ffffff',
      inputBorder: isDark ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.08)',
      inputBg: isDark ? 'rgba(255,255,255,.04)' : '#ffffff',
      inputShadow: isDark ? 'none' : '0 1px 4px rgba(0,0,0,.08), inset 0 1px 0 rgba(255,255,255,.85)',
      sendBg: isDark ? 'rgba(255,255,255,.06)' : '#ffffff',
      sendBorder: isDark ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.08)',
      sendShadow: isDark ? '0 1px 3px rgba(0,0,0,.24), inset 0 1px 0 rgba(255,255,255,.06)' : '0 1px 3px rgba(0,0,0,.1), inset 0 1px 0 rgba(255,255,255,.85)',
      sendStroke: isDark ? '#e2e8f0' : sbDark,
      /* Attach button: matches chatAttach style */
      attachBg: isDark ? 'rgba(255,255,255,.06)' : '#ffffff',
      attachBorder: isDark ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.08)',
      attachShadow: isDark ? '0 1px 3px rgba(0,0,0,.24), inset 0 1px 0 rgba(255,255,255,.06)' : '0 1px 3px rgba(0,0,0,.1), inset 0 1px 0 rgba(255,255,255,.85)',
      attachStroke: isDark ? '#e2e8f0' : sbDark,
      scrollThumb: isDark ? 'rgba(255,255,255,.2)' : 'rgba(0,0,0,.18)',
      cloudBg: isDark ? 'color-mix(in srgb, ' + sidebar + ' 88%, #ffffff 12%)' : '#ffffff',
      cloudBorder: isDark ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.06)',
      cloudTopBorder: isDark ? 'rgba(255,255,255,.12)' : 'rgba(255,255,255,.9)',
      cloudShadow: isDark
        ? 'inset 0 2px 4px rgba(255,255,255,.08), inset 0 -4px 8px rgba(0,0,0,.2), 0 1px 3px rgba(0,0,0,.12), 0 4px 16px rgba(0,0,0,.18)'
        : 'inset 0 2px 4px rgba(255,255,255,.9), inset 0 -4px 8px rgba(0,0,0,.07), 0 1px 3px rgba(0,0,0,.08), 0 4px 16px rgba(0,0,0,.12)',
      cloudTailShadow: isDark
        ? '0 4px 16px rgba(0,0,0,.18)'
        : '0 4px 16px rgba(0,0,0,.12)'
    };
  }

  // ========== Buddy SVG Icon — matches buddy_landing.html 3D model ==========
  /* Farben aus buddy_landing.html Three.js model:
     Body: C_CORE=#20F5E0, C_INNER=#22E8C8, C_MID=#27DEDE, C_GLOW=#80FFD0
     Belly: C_BELLY=#FFB8C8 (rosa), C_BELLY_SOFT=#FFC0D0
     Cheeks: C_CHEEK=#FF8FA0
     Eyes: C_EYE_PUPIL=#050E1A, C_EYE_WHITE=#FFFFFF
     Arms: C_MID1=#2895E5, Feet: C_MID=#27DEDE */
  const BUDDY_SVG = `<svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <radialGradient id="bBodyGrad" cx="50%" cy="40%" r="55%">
        <stop offset="0%" stop-color="#80FFD0"/>
        <stop offset="50%" stop-color="#22E8C8"/>
        <stop offset="100%" stop-color="#20F5E0"/>
      </radialGradient>
      <radialGradient id="bHeadGrad" cx="50%" cy="35%" r="55%">
        <stop offset="0%" stop-color="#80FFD0"/>
        <stop offset="60%" stop-color="#22E8C8"/>
        <stop offset="100%" stop-color="#20F5E0"/>
      </radialGradient>
    </defs>
    <!-- body -->
    <ellipse cx="16" cy="19" rx="7" ry="6" fill="url(#bBodyGrad)"/>
    <!-- head -->
    <circle cx="16" cy="12" r="7.5" fill="url(#bHeadGrad)"/>
    <!-- ears -->
    <ellipse cx="10.5" cy="5.5" rx="1.8" ry="3" fill="#22E8C8" transform="rotate(-10 10.5 5.5)"/>
    <ellipse cx="21.5" cy="5.5" rx="1.8" ry="3" fill="#22E8C8" transform="rotate(10 21.5 5.5)"/>
    <ellipse cx="10.5" cy="5.5" rx="1.2" ry="2.2" fill="#80FFD0" transform="rotate(-10 10.5 5.5)"/>
    <ellipse cx="21.5" cy="5.5" rx="1.2" ry="2.2" fill="#80FFD0" transform="rotate(10 21.5 5.5)"/>
    <!-- belly rosa -->
    <ellipse cx="16" cy="20" rx="4" ry="3.5" fill="#FFB8C8" opacity=".55"/>
    <ellipse cx="16" cy="19.5" rx="3" ry="2.5" fill="#FFC0D0" opacity=".4"/>
    <!-- eyes -->
    <ellipse cx="13" cy="11.5" rx="2" ry="2.2" fill="#fff"/>
    <ellipse cx="19" cy="11.5" rx="2" ry="2.2" fill="#fff"/>
    <circle cx="13.3" cy="11.8" r="1.3" fill="#050E1A"/>
    <circle cx="19.3" cy="11.8" r="1.3" fill="#050E1A"/>
    <!-- eye glints -->
    <circle cx="13.8" cy="11" r=".5" fill="#fff"/>
    <circle cx="19.8" cy="11" r=".5" fill="#fff"/>
    <!-- cheeks -->
    <ellipse cx="9.8" cy="14" rx="1.8" ry="1.2" fill="#FF8FA0" opacity=".5"/>
    <ellipse cx="22.2" cy="14" rx="1.8" ry="1.2" fill="#FF8FA0" opacity=".5"/>
    <!-- mouth -->
    <path d="M14 15.5 Q16 17.5 18 15.5" fill="none" stroke="#050E1A" stroke-width=".8" stroke-linecap="round"/>
    <!-- arms -->
    <ellipse cx="7.5" cy="18" rx="2" ry="1.2" fill="#2895E5" transform="rotate(-15 7.5 18)"/>
    <ellipse cx="24.5" cy="18" rx="2" ry="1.2" fill="#2895E5" transform="rotate(15 24.5 18)"/>
    <!-- feet -->
    <ellipse cx="13" cy="24.5" rx="2.2" ry="1.3" fill="#27DEDE"/>
    <ellipse cx="19" cy="24.5" rx="2.2" ry="1.3" fill="#27DEDE"/>
  </svg>`;

  // ========== CSS ==========
  const style = document.createElement('style');
  style.textContent = `
    #buddyWidget{position:fixed;z-index:99999;cursor:grab;user-select:none;-webkit-user-select:none}
    #buddyWidget.bw-local{position:absolute}
    #buddyWidget.dragging{cursor:grabbing}
    #buddyWidgetIcon{width:52px;height:52px;border-radius:50%;display:flex;align-items:center;justify-content:center;
      box-shadow:0 2px 12px var(--bw-shadow);border:2px solid var(--bw-iconBorder);background:var(--bw-iconBg);transition:transform .2s,box-shadow .2s}
    #buddyWidgetIcon:hover{transform:scale(1.08);box-shadow:0 4px 18px var(--bw-shadow)}
    #buddyWidgetIcon svg{width:34px;height:34px}
    #buddyWidgetBadge{position:absolute;top:-2px;right:-2px;width:14px;height:14px;border-radius:50%;background:#ef4444;
      border:2px solid var(--bw-iconBg);display:none;animation:bwPulse 2s infinite}
    @keyframes bwPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.3)}}
    @keyframes bwThink{0%,100%{opacity:.6}50%{opacity:1}}
    #buddyWidget.thinking #buddyWidgetIcon{animation:bwThink 1.2s ease-in-out infinite}
    #buddyWidgetBubble{position:fixed;width:320px;height:420px;min-width:260px;min-height:200px;border-radius:12px;
      background:var(--bw-bg);border:1px solid var(--bw-border);box-shadow:0 4px 24px var(--bw-shadow);
      display:none;flex-direction:column;overflow:hidden;z-index:99998}
    #buddyWidgetBubble.open{display:flex}
    #buddyWidgetBubble.bw-dragging{cursor:grabbing;user-select:none}
    #buddyWidgetBubble.bw-resizing{user-select:none}
    .bwResize{position:absolute;z-index:2}
    .bwResize--n{top:-4px;left:8px;right:8px;height:8px;cursor:n-resize}
    .bwResize--s{bottom:-4px;left:8px;right:8px;height:8px;cursor:s-resize}
    .bwResize--w{left:-4px;top:8px;bottom:8px;width:8px;cursor:w-resize}
    .bwResize--e{right:-4px;top:8px;bottom:8px;width:8px;cursor:e-resize}
    .bwResize--nw{top:-4px;left:-4px;width:12px;height:12px;cursor:nw-resize}
    .bwResize--ne{top:-4px;right:-4px;width:12px;height:12px;cursor:ne-resize}
    .bwResize--sw{bottom:-4px;left:-4px;width:12px;height:12px;cursor:sw-resize}
    .bwResize--se{bottom:-4px;right:-4px;width:12px;height:12px;cursor:se-resize}
    .bwHeader{display:flex;align-items:center;padding:10px 12px;border-bottom:1px solid var(--bw-border);gap:8px;background:var(--bw-headerBg);border-radius:12px 12px 0 0;cursor:grab}
    .bwHeader__dot{width:8px;height:8px;border-radius:50%;background:var(--bw-accent);flex-shrink:0}
    .bwHeader__dot[data-state="ok"]{background:var(--bw-accent)}
    .bwHeader__dot[data-state="warn"]{background:#f59e0b}
    .bwHeader__dot[data-state="offline"]{background:#9ca3af}
    .bwHeader__dot[data-state="unknown"]{background:#94a3b8}
    .bwHeader__name{font-size:13px;font-weight:700;color:var(--bw-text);flex:1}
    .bwHeader__close{background:none;border:none;font-size:18px;color:var(--bw-textMuted);cursor:pointer;padding:0 2px;line-height:1}
    .bwHeader__close:hover{color:var(--bw-text)}
    .bwMessages{flex:1;min-height:0;overflow-y:auto;padding:8px 10px;display:flex;flex-direction:column;gap:6px;
      scrollbar-width:thin;scrollbar-color:var(--bw-scrollThumb) transparent;background:var(--bw-messagesBg)}
    .bwMessages::-webkit-scrollbar{width:5px}
    .bwMessages::-webkit-scrollbar-track{background:transparent}
    .bwMessages::-webkit-scrollbar-thumb{background:var(--bw-scrollThumb);border-radius:999px}
    .bwMsg{max-width:85%;padding:6px 10px;border-radius:10px;font-size:12px;line-height:1.45;word-wrap:break-word;color:var(--bw-text)}
    .bwMsg--user{background:var(--bw-userBg);align-self:flex-end;border-bottom-right-radius:3px;
      border:1px solid var(--bw-userBorder);box-shadow:var(--bw-userShadow)}
    .bwMsg--buddy{background:var(--bw-buddyBg);align-self:flex-start;border-bottom-left-radius:3px;
      border:1px solid var(--bw-buddyBorder);box-shadow:var(--bw-buddyShadow)}
    .bwMsg__footer{display:flex;align-items:center;gap:6px;margin-top:4px;justify-content:flex-end}
    .bwMsg__time{font-size:9px;color:var(--bw-textMuted)}
    .bwInput{display:flex;gap:6px;border-top:1px solid var(--bw-border);padding:8px;align-items:flex-end}
    .bwInput__attach{width:30px;height:30px;border:1px solid var(--bw-attachBorder);border-radius:8px;
      background:var(--bw-attachBg);box-shadow:var(--bw-attachShadow);
      cursor:pointer;padding:0;display:flex;align-items:center;justify-content:center;flex-shrink:0;
      transition:background .15s ease, border-color .15s ease, box-shadow .15s ease}
    .bwInput__attach:hover{filter:brightness(1.05);box-shadow:0 2px 5px rgba(0,0,0,.12)}
    .bwInput__attach svg{width:14px;height:14px;fill:none;stroke:var(--bw-attachStroke);stroke-width:2;stroke-linecap:round}
    .bwInput textarea{flex:1;border:1px solid var(--bw-inputBorder);border-radius:8px;padding:6px 8px;font-size:12px;resize:none;
      background:var(--bw-inputBg);color:var(--bw-text);font-family:inherit;outline:none;min-height:32px;max-height:64px;
      box-shadow:var(--bw-inputShadow);scrollbar-width:thin;scrollbar-color:var(--bw-scrollThumb) transparent}
    .bwInput textarea::-webkit-scrollbar{width:5px}
    .bwInput textarea::-webkit-scrollbar-track{background:transparent}
    .bwInput textarea::-webkit-scrollbar-thumb{background:var(--bw-scrollThumb);border-radius:999px}
    .bwInput textarea::placeholder{color:var(--bw-textMuted)}
    .bwInput__send{width:30px;height:30px;border:1px solid var(--bw-sendBorder);border-radius:8px;
      background:var(--bw-sendBg);box-shadow:var(--bw-sendShadow);
      cursor:pointer;padding:0;display:flex;align-items:center;justify-content:center;flex-shrink:0;
      transition:background .15s ease, border-color .15s ease, box-shadow .15s ease}
    .bwInput__send:hover{filter:brightness(1.05);box-shadow:0 2px 5px rgba(0,0,0,.12)}
    .bwInput__send svg{width:14px;height:14px;fill:none;stroke:var(--bw-sendStroke);stroke-width:2.5;stroke-linecap:round;stroke-linejoin:round}
    .bwInput__fileInfo{display:flex;align-items:center;gap:4px;padding:2px 6px;font-size:10px;color:var(--bw-textMuted);width:100%}
    .bwInput__fileInfo button{background:none;border:none;color:var(--bw-textMuted);cursor:pointer;font-size:14px;padding:0 2px}
    .bwInput__fileInfo button:hover{color:var(--bw-text)}
    .bwAttachPreview{display:none;flex-wrap:wrap;gap:4px;padding:4px 8px;border-top:1px solid var(--bw-border);background:var(--bw-inputBg)}
    .bwAttachPreview.has-items{display:flex}
    .bwAttachPreview__item{position:relative;width:48px;height:48px;border-radius:5px;overflow:hidden;border:1px solid var(--bw-border)}
    .bwAttachPreview__item img{width:100%;height:100%;object-fit:cover}
    .bwAttachPreview__item--file{display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;color:var(--bw-textMuted);background:var(--bw-bubbleBg)}
    .bwAttachPreview__remove{position:absolute;top:-2px;right:-2px;width:14px;height:14px;border-radius:50%;background:rgba(0,0,0,.6);color:#fff;border:none;font-size:10px;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center}
    .bwCopyBtn{flex-shrink:0;width:16px;height:16px;border:none;background:transparent;cursor:pointer;opacity:.3;transition:opacity .15s ease,background .12s ease;padding:0;display:flex;align-items:center;justify-content:center;border-radius:3px}
    .bwCopyBtn:hover{opacity:.7}
    .bwCopyBtn svg{width:10px;height:10px;fill:none;stroke:var(--bw-text);stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
    .bwCopyBtn--done svg{stroke:var(--bw-accent)}
    .bwCopyBtn--done{opacity:.7}
    .bwReactBtn{flex-shrink:0;width:16px;height:16px;border:none;background:transparent;cursor:pointer;border-radius:3px;display:flex;align-items:center;justify-content:center;opacity:.3;transition:opacity .15s ease,color .15s ease;padding:0;font-size:11px;line-height:1}
    .bwReactBtn:hover{opacity:.7}
    .bwReactBtn--active{opacity:.7 !important}
    .bwReactBtn--up.bwReactBtn--active{color:#22c55e}
    .bwReactBtn--down.bwReactBtn--active{color:#ef4444}

    #buddyWidget.bw-cloudMode{width:52px;height:52px;overflow:visible}
    #buddyWidget.bw-cloudMode #buddyWidgetBubble{
      position:absolute;width:min(272px, calc(100vw - 34px));max-width:272px;height:auto;min-width:0;min-height:0;max-height:292px;
      right:-10px;bottom:66px;border-radius:28px;background:var(--bw-cloudBg);
      border:1px solid var(--bw-cloudBorder);border-top:1px solid var(--bw-cloudTopBorder);box-shadow:var(--bw-cloudShadow);
      overflow:visible;isolation:isolate;
    }
    #buddyWidget.bw-cloudMode #buddyWidgetBubble::after{
      content:'';position:absolute;right:20px;bottom:-10px;width:24px;height:24px;transform:rotate(45deg);
      background:var(--bw-cloudBg);border-right:1px solid var(--bw-cloudBorder);border-bottom:1px solid var(--bw-cloudBorder);
      box-shadow:var(--bw-cloudTailShadow);z-index:0;
    }
    #buddyWidget.bw-cloudMode #buddyWidgetBubble::before{
      content:'';position:absolute;inset:0;border-radius:inherit;pointer-events:none;
      box-shadow:inset 0 1px 0 var(--bw-cloudTopBorder);
    }
    #buddyWidget.bw-cloudMode #buddyWidgetBubble.bw-pos-below{bottom:auto;top:66px}
    #buddyWidget.bw-cloudMode #buddyWidgetBubble.bw-pos-below::after{
      top:-10px;bottom:auto;transform:rotate(225deg);border-right:none;border-bottom:none;border-left:1px solid var(--bw-cloudBorder);border-top:1px solid var(--bw-cloudBorder);
    }
    #buddyWidget.bw-cloudMode #buddyWidgetBubble.bw-align-left{left:-12px;right:auto}
    #buddyWidget.bw-cloudMode #buddyWidgetBubble.bw-align-left::after{left:18px;right:auto}
    #buddyWidget.bw-cloudMode .bwResize{display:none}
    #buddyWidget.bw-cloudMode .bwHeader{
      padding:12px 14px 6px;border-bottom:none;background:transparent;border-radius:28px 28px 0 0;cursor:default;position:relative;z-index:1;
    }
    #buddyWidget.bw-cloudMode .bwHeader__close{display:none}
    #buddyWidget.bw-cloudMode .bwMessages{
      padding:2px 12px 10px;background:transparent;max-height:150px;min-height:44px;gap:8px;position:relative;z-index:1;
    }
    #buddyWidget.bw-cloudMode .bwMsg{max-width:100%;font-size:11px;border-radius:20px;padding:8px 10px}
    #buddyWidget.bw-cloudMode .bwMsg--user{border-radius:22px 22px 12px 22px}
    #buddyWidget.bw-cloudMode .bwMsg--buddy{border-radius:22px 22px 22px 12px}
    #buddyWidget.bw-cloudMode .bwMsg__footer{justify-content:flex-start;gap:4px}
    #buddyWidget.bw-cloudMode .bwCopyBtn,
    #buddyWidget.bw-cloudMode .bwReactBtn{display:none}
    #buddyWidget.bw-cloudMode .bwInput{
      padding:10px 12px 12px;border-top:none;background:transparent;position:relative;z-index:1;
    }
    #buddyWidget.bw-cloudMode .bwInput textarea{
      min-height:38px;max-height:78px;border-radius:16px;padding:8px 12px;font-size:12px;
    }
    #buddyWidget.bw-cloudMode .bwInput__send{
      width:34px;height:34px;border-radius:12px;
    }
    #buddyWidget.bw-cloudMode .bwAttachPreview{display:none !important}
  `;
  document.head.appendChild(style);

  // ========== DOM ==========
  const widget = document.createElement('div');
  widget.id = 'buddyWidget';
  if(mountedInSurface){
    widget.classList.add('bw-local');
    if(getComputedStyle(mountRoot).position === 'static') mountRoot.style.position = 'relative';
  }
  if(cloudMode) widget.classList.add('bw-cloudMode');

  widget.innerHTML = `
    <div id="buddyWidgetIcon">
      ${BUDDY_SVG}
      <div id="buddyWidgetBadge"></div>
    </div>
    <div id="buddyWidgetBubble">
      <div class="bwResize bwResize--n"></div><div class="bwResize bwResize--s"></div>
      <div class="bwResize bwResize--w"></div><div class="bwResize bwResize--e"></div>
      <div class="bwResize bwResize--nw"></div><div class="bwResize bwResize--ne"></div>
      <div class="bwResize bwResize--sw"></div><div class="bwResize bwResize--se"></div>
      <div class="bwHeader">
        <span class="bwHeader__dot"></span>
        <span class="bwHeader__name">Buddy</span>
        <button class="bwHeader__close">&times;</button>
      </div>
      <div class="bwMessages" id="bwMessages"></div>
      <div class="bwAttachPreview" id="bwAttachPreview"></div>
      <div class="bwInput">
        <button class="bwInput__attach" id="bwAttach" title="Anhang"><svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></button>
        <textarea id="bwInput" placeholder="Nachricht an Buddy..." rows="1"></textarea>
        <button class="bwInput__send" id="bwSend"><svg viewBox="0 0 24 24"><path d="M12 19V5M5 12l7-7 7 7"/></svg></button>
      </div>
      <input type="file" id="bwFileInput" style="display:none" accept="image/png,image/jpeg,image/gif,image/webp,application/pdf,.txt,.json">
    </div>`;
  mountRoot.appendChild(widget);

  const icon = document.getElementById('buddyWidgetIcon');
  const bubble = document.getElementById('buddyWidgetBubble');
  const badge = document.getElementById('buddyWidgetBadge');
  const messagesEl = document.getElementById('bwMessages');
  const inputEl = document.getElementById('bwInput');
  const sendBtn = document.getElementById('bwSend');
  const closeBtn = widget.querySelector('.bwHeader__close');
  const headerDot = widget.querySelector('.bwHeader__dot');
  const headerName = widget.querySelector('.bwHeader__name');
  const attachBtn = document.getElementById('bwAttach');
  const fileInput = document.getElementById('bwFileInput');
  /* pendingFiles replaced by bwPendingAttachments below */

  function readStoredJson(key){
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch(e){
      return null;
    }
  }

  function getBounds(){
    if(mountedInSurface){
      const rect = mountRoot.getBoundingClientRect();
      return {width: rect.width, height: rect.height, left: rect.left, top: rect.top};
    }
    return {width: window.innerWidth, height: window.innerHeight, left: 0, top: 0};
  }

  function clamp(value, min, max){
    return Math.max(min, Math.min(max, value));
  }

  function applyWidgetPosition(rawPos){
    const bounds = getBounds();
    const iconSize = 52;
    if(mountedInSurface){
      const fallback = { right: 18, top: 74, ...widgetDefaultPosition };
      const left = Number.isFinite(Number(rawPos && rawPos.left))
        ? Number(rawPos.left)
        : (Number.isFinite(Number(rawPos && rawPos.right))
          ? bounds.width - iconSize - Number(rawPos.right)
          : bounds.width - iconSize - Number(fallback.right || 18));
      const top = Number.isFinite(Number(rawPos && rawPos.top))
        ? Number(rawPos.top)
        : (Number.isFinite(Number(rawPos && rawPos.bottom))
          ? bounds.height - iconSize - Number(rawPos.bottom)
          : Number(fallback.top || 74));
      widget.style.left = clamp(left, 0, Math.max(0, bounds.width - iconSize)) + 'px';
      widget.style.top = clamp(top, 0, Math.max(0, bounds.height - iconSize)) + 'px';
      widget.style.right = 'auto';
      widget.style.bottom = 'auto';
      return;
    }

    const fallback = { right: 24, bottom: 24, ...widgetDefaultPosition };
    const right = Number.isFinite(Number(rawPos && rawPos.right)) ? Number(rawPos.right) : Number(fallback.right || 24);
    const bottom = Number.isFinite(Number(rawPos && rawPos.bottom)) ? Number(rawPos.bottom) : Number(fallback.bottom || 24);
    widget.style.right = clamp(right, 0, Math.max(0, bounds.width - iconSize)) + 'px';
    widget.style.bottom = clamp(bottom, 0, Math.max(0, bounds.height - iconSize)) + 'px';
    widget.style.left = 'auto';
    widget.style.top = 'auto';
  }

  function currentWidgetPosition(){
    if(mountedInSurface){
      return {
        left: parseInt(widget.style.left, 10) || 0,
        top: parseInt(widget.style.top, 10) || 0
      };
    }
    return {
      right: parseInt(widget.style.right, 10) || 0,
      bottom: parseInt(widget.style.bottom, 10) || 0
    };
  }

  applyWidgetPosition(readStoredJson(POS_KEY) || widgetDefaultPosition);

  // ========== Theme Sync ==========
  function applyTheme(){
    const c = getThemeColors();
    const r = widget.style;
    r.setProperty('--bw-bg', c.bg);
    r.setProperty('--bw-border', c.border);
    r.setProperty('--bw-text', c.text);
    r.setProperty('--bw-textMuted', c.textMuted);
    r.setProperty('--bw-bubbleBg', c.bubbleBg);
    r.setProperty('--bw-userBg', c.userBg);
    r.setProperty('--bw-userBorder', c.userBorder);
    r.setProperty('--bw-userShadow', c.userShadow);
    r.setProperty('--bw-buddyBg', c.buddyBg);
    r.setProperty('--bw-buddyBorder', c.buddyBorder);
    r.setProperty('--bw-buddyShadow', c.buddyShadow);
    r.setProperty('--bw-accent', c.accent);
    r.setProperty('--bw-iconBg', c.iconBg);
    r.setProperty('--bw-iconBorder', c.iconBorder);
    r.setProperty('--bw-shadow', c.shadow);
    r.setProperty('--bw-headerBg', c.headerBg);
    r.setProperty('--bw-messagesBg', c.messagesBg);
    r.setProperty('--bw-inputBorder', c.inputBorder);
    r.setProperty('--bw-inputBg', c.inputBg);
    r.setProperty('--bw-inputShadow', c.inputShadow);
    r.setProperty('--bw-sendBg', c.sendBg);
    r.setProperty('--bw-sendBorder', c.sendBorder);
    r.setProperty('--bw-sendShadow', c.sendShadow);
    r.setProperty('--bw-sendStroke', c.sendStroke);
    r.setProperty('--bw-attachBg', c.attachBg);
    r.setProperty('--bw-attachBorder', c.attachBorder);
    r.setProperty('--bw-attachShadow', c.attachShadow);
    r.setProperty('--bw-attachStroke', c.attachStroke);
    r.setProperty('--bw-scrollThumb', c.scrollThumb);
    r.setProperty('--bw-cloudBg', c.cloudBg);
    r.setProperty('--bw-cloudBorder', c.cloudBorder);
    r.setProperty('--bw-cloudTopBorder', c.cloudTopBorder);
    r.setProperty('--bw-cloudShadow', c.cloudShadow);
    r.setProperty('--bw-cloudTailShadow', c.cloudTailShadow);
  }
  applyTheme();
  new MutationObserver(applyTheme).observe(document.documentElement, {attributes:true, attributeFilter:['data-theme']});

  // ========== Dragging ==========
  let isDragging = false, dragStartX, dragStartY, startRight, startBottom, startLeft, startTop, hasMoved;
  icon.addEventListener('mousedown', e => {
    isDragging = true; hasMoved = false;
    dragStartX = e.clientX; dragStartY = e.clientY;
    if(mountedInSurface){
      startLeft = parseInt(widget.style.left, 10) || 0;
      startTop = parseInt(widget.style.top, 10) || 0;
    } else {
      startRight = parseInt(widget.style.right, 10) || 0;
      startBottom = parseInt(widget.style.bottom, 10) || 0;
    }
    widget.classList.add('dragging');
    e.preventDefault();
  });
  document.addEventListener('mousemove', e => {
    if(!isDragging) return;
    const dx = e.clientX - dragStartX;
    const dy = e.clientY - dragStartY;
    if(Math.abs(dx) > 3 || Math.abs(dy) > 3) hasMoved = true;
    if(mountedInSurface){
      const bounds = getBounds();
      widget.style.left = clamp(startLeft + dx, 0, Math.max(0, bounds.width - 52)) + 'px';
      widget.style.top = clamp(startTop + dy, 0, Math.max(0, bounds.height - 52)) + 'px';
      return;
    }
    const maxR = window.innerWidth - 60;
    const maxB = window.innerHeight - 60;
    widget.style.right = Math.max(0, Math.min(maxR, startRight - dx)) + 'px';
    widget.style.bottom = Math.max(0, Math.min(maxB, startBottom - dy)) + 'px';
  });
  document.addEventListener('mouseup', () => {
    if(!isDragging) return;
    isDragging = false;
    widget.classList.remove('dragging');
    localStorage.setItem(POS_KEY, JSON.stringify(currentWidgetPosition()));
  });

  // ========== Messages ==========
  let messages = [];
  let unreadCount = 0;
  const MAX_WIDGET_MESSAGES = 100;
  const BUDDY_WIDGET_HIDDEN_META_TYPES = new Set([
    'context_restore',
    'heartbeat_check',
    'restart_wake',
    'restart_warn',
    'system',
    'automation_message'
  ]);
  const BUDDY_WIDGET_HIDDEN_BUDDY_PREFIXES = [
    /^HEARTBEAT_CHECK verarbeitet\./i,
    /^CONTEXT RESTORE und HEARTBEAT_CHECK verarbeitet\./i,
    /^Buddy ist wieder registriert\./i
  ];

  function escapeHtml(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  function formatTime(ts){
    try { const d = new Date(ts); return d.toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'}); }
    catch(e){ return ''; }
  }

  function renderMessages(){
    messagesEl.innerHTML = '';
    messages.forEach(m => {
      const isUser = m.from === 'user';
      const div = document.createElement('div');
      div.className = 'bwMsg bwMsg--' + (isUser ? 'user' : 'buddy');
      const textSpan = document.createElement('span');
      textSpan.textContent = m.content;
      div.appendChild(textSpan);

      // Footer: [timestamp] [copyBtn] [thumbUp] [thumbDown] — identical to Management Board
      const footer = document.createElement('div');
      footer.className = 'bwMsg__footer';

      // Timestamp
      const ts = formatTime(m.timestamp);
      if(ts){
        const timeEl = document.createElement('span');
        timeEl.className = 'bwMsg__time';
        timeEl.textContent = ts;
        footer.appendChild(timeEl);
      }

      // Copy button
      const copyBtn = document.createElement('button');
      copyBtn.className = 'bwCopyBtn';
      copyBtn.title = 'Kopieren';
      copyBtn.innerHTML = '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
      copyBtn.addEventListener('click', e => {
        e.stopPropagation();
        navigator.clipboard.writeText(m.content).then(() => {
          copyBtn.classList.add('bwCopyBtn--done');
          copyBtn.innerHTML = '<svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>';
          setTimeout(() => {
            copyBtn.classList.remove('bwCopyBtn--done');
            copyBtn.innerHTML = '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
          }, 1500);
        });
      });
      footer.appendChild(copyBtn);

      // Thumbs up/down reaction buttons
      const thumbUp = document.createElement('button');
      thumbUp.className = 'bwReactBtn bwReactBtn--up';
      thumbUp.title = 'Gut';
      thumbUp.textContent = '\u{1F44D}';
      const thumbDown = document.createElement('button');
      thumbDown.className = 'bwReactBtn bwReactBtn--down';
      thumbDown.title = 'Schlecht';
      thumbDown.textContent = '\u{1F44E}';

      thumbUp.addEventListener('click', e => {
        e.stopPropagation();
        const isActive = thumbUp.classList.contains('bwReactBtn--active');
        thumbUp.classList.toggle('bwReactBtn--active');
        thumbDown.classList.remove('bwReactBtn--active');
        if(m.id){
          fetch(API + '/messages/' + m.id + '/reaction', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({reaction: isActive ? null : 'thumbs_up', from: 'user'})
          }).catch(() => {});
        }
      });
      thumbDown.addEventListener('click', e => {
        e.stopPropagation();
        const isActive = thumbDown.classList.contains('bwReactBtn--active');
        thumbDown.classList.toggle('bwReactBtn--active');
        thumbUp.classList.remove('bwReactBtn--active');
        if(m.id){
          fetch(API + '/messages/' + m.id + '/reaction', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({reaction: isActive ? null : 'thumbs_down', from: 'user'})
          }).catch(() => {});
        }
      });

      // Apply existing reaction state if present
      if(m.reactions){
        const userReaction = (m.reactions || []).find(r => r.from === 'user');
        if(userReaction){
          if(userReaction.reaction === 'thumbs_up') thumbUp.classList.add('bwReactBtn--active');
          if(userReaction.reaction === 'thumbs_down') thumbDown.classList.add('bwReactBtn--active');
        }
      }

      footer.appendChild(thumbUp);
      footer.appendChild(thumbDown);

      div.appendChild(footer);
      messagesEl.appendChild(div);
    });
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function buddyMessageFingerprint(msg){
    if(!msg) return '';
    const clientNonce = msg.meta && (msg.meta.client_nonce || msg.meta.clientNonce);
    if(clientNonce) return 'client_nonce::' + String(clientNonce);
    if(msg.id) return 'id::' + String(msg.id);
    return String([msg.timestamp || '', msg.from || '', msg.to || '', msg.content || ''].join('::'));
  }

  function latestBuddyFingerprint(list){
    const lastBuddyMsg = (list || []).filter(m => m.from === 'buddy').slice(-1)[0];
    return buddyMessageFingerprint(lastBuddyMsg);
  }

  function isBuddyOperationalMessage(msg){
    if(!msg) return false;
    const metaType = String((msg.meta && msg.meta.type) || '').trim();
    if(metaType && BUDDY_WIDGET_HIDDEN_META_TYPES.has(metaType)) return true;
    const content = String(msg.content || '').trim();
    if(content.startsWith('[CONTEXT RESTORE]') || content.startsWith('[HEARTBEAT_CHECK]')) return true;
    if(msg.from !== 'buddy') return false;
    return BUDDY_WIDGET_HIDDEN_BUDDY_PREFIXES.some((pattern) => pattern.test(content));
  }

  function isBuddyWidgetVisibleMessage(msg){
    return !isBuddyOperationalMessage(msg);
  }

  function mergeBuddyMessages(currentList, nextList){
    const merged = new Map();
    (currentList || []).forEach(msg => {
      merged.set(buddyMessageFingerprint(msg), msg);
    });
    (nextList || []).forEach(msg => {
      merged.set(buddyMessageFingerprint(msg), msg);
    });
    return Array.from(merged.values())
      .sort((left, right) => {
        const tsCmp = String(left.timestamp || '').localeCompare(String(right.timestamp || ''));
        if(tsCmp !== 0) return tsCmp;
        return Number(left.id || 0) - Number(right.id || 0);
      })
      .slice(-MAX_WIDGET_MESSAGES);
  }

  function addMessage(msg){
    messages = mergeBuddyMessages(messages, [msg]);
    renderMessages();
  }

  function setBuddyPresence(state, detail){
    headerDot.dataset.state = state;
    const title = detail ? 'Buddy: ' + detail : 'Buddy';
    headerDot.title = title;
    headerName.title = title;
  }

  async function refreshBuddyPresence(){
    try {
      const res = await bridgeFetch(API + '/agents/buddy', { signal: AbortSignal.timeout(3000) });
      if(!res.ok) throw new Error('status ' + res.status);
      const data = await res.json();
      const rawStatus = String(data.status || '').trim() || 'offline';
      if(data.online){
        setBuddyPresence('ok', 'online');
        return;
      }
      if(data.active || data.tmux_alive || ['waiting', 'running', 'busy', 'disconnected', 'starting'].includes(rawStatus)){
        setBuddyPresence('warn', rawStatus);
        return;
      }
      setBuddyPresence('offline', rawStatus);
    } catch(e){
      setBuddyPresence('unknown', 'status unavailable');
    }
  }

  function showUnread(){
    badge.style.display = unreadCount > 0 ? 'block' : 'none';
  }

  // ========== Open / Close ==========
  let bubbleOpen = false;

  function positionBubble(){
    if(cloudMode){
      const bounds = getBounds();
      const wr = widget.getBoundingClientRect();
      const iconLeft = wr.left - bounds.left;
      const iconTop = wr.top - bounds.top;
      const bubbleWidth = Math.min(272, Math.max(228, bounds.width - 24));
      bubble.style.width = bubbleWidth + 'px';
      bubble.style.height = 'auto';
      bubble.classList.remove('bw-pos-below', 'bw-align-left');
      if(iconTop < 224) bubble.classList.add('bw-pos-below');
      if(iconLeft < bubbleWidth - 72) bubble.classList.add('bw-align-left');
      return;
    }
    /* Restore size */
    const savedSize = localStorage.getItem(BUBBLE_SIZE_KEY);
    if(savedSize){
      const bs = JSON.parse(savedSize);
      bubble.style.width = Math.max(260, bs.w) + 'px';
      bubble.style.height = Math.max(200, bs.h) + 'px';
    }
    const bw = parseInt(bubble.style.width) || 320;
    const bh = parseInt(bubble.style.height) || 420;
    /* Restore position */
    const saved = localStorage.getItem(BUBBLE_POS_KEY);
    if(saved){
      const bp = JSON.parse(saved);
      bubble.style.left = Math.max(0, Math.min(window.innerWidth - bw, bp.left)) + 'px';
      bubble.style.top = Math.max(0, Math.min(window.innerHeight - 100, bp.top)) + 'px';
    } else {
      const wr = widget.getBoundingClientRect();
      bubble.style.left = Math.max(0, wr.right - bw) + 'px';
      bubble.style.top = Math.max(0, wr.top - bh - 10) + 'px';
    }
  }

  function openBubble(){
    bubble.classList.add('open');
    bubbleOpen = true;
    positionBubble();
    unreadCount = 0; showUnread();
    widget.classList.remove('thinking');
    refreshBuddyPresence();
    inputEl.focus();
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function closeBubble(){
    bubble.classList.remove('open');
    bubbleOpen = false;
  }

  icon.addEventListener('click', () => {
    if(hasMoved) return;
    if(bubbleOpen) closeBubble(); else openBubble();
  });
  closeBtn.addEventListener('click', closeBubble);
  document.addEventListener('mousedown', e => {
    if(!cloudMode || !bubbleOpen) return;
    if(widget.contains(e.target)) return;
    closeBubble();
  });
  window.addEventListener('resize', () => {
    applyWidgetPosition(currentWidgetPosition());
    if(bubbleOpen) positionBubble();
  });

  // ========== Bubble Drag (via Header) ==========
  let bubbleDragging = false, bubbleDragX, bubbleDragY, bubbleStartLeft, bubbleStartTop;
  const headerEl = widget.querySelector('.bwHeader');
  if(!cloudMode){
    headerEl.addEventListener('mousedown', e => {
      if(e.target.closest('.bwHeader__close')) return;
      bubbleDragging = true;
      bubbleDragX = e.clientX; bubbleDragY = e.clientY;
      bubbleStartLeft = bubble.getBoundingClientRect().left;
      bubbleStartTop = bubble.getBoundingClientRect().top;
      bubble.classList.add('bw-dragging');
      e.preventDefault();
    });
    document.addEventListener('mousemove', e => {
      if(!bubbleDragging) return;
      const dx = e.clientX - bubbleDragX;
      const dy = e.clientY - bubbleDragY;
      const bw = bubble.offsetWidth || 320;
      const newLeft = Math.max(0, Math.min(window.innerWidth - bw, bubbleStartLeft + dx));
      const newTop = Math.max(0, Math.min(window.innerHeight - 100, bubbleStartTop + dy));
      bubble.style.left = newLeft + 'px';
      bubble.style.top = newTop + 'px';
    });
    document.addEventListener('mouseup', () => {
      if(!bubbleDragging) return;
      bubbleDragging = false;
      bubble.classList.remove('bw-dragging');
      localStorage.setItem(BUBBLE_POS_KEY, JSON.stringify({left:parseInt(bubble.style.left), top:parseInt(bubble.style.top)}));
    });
  }

  // ========== Bubble Resize (via edge/corner handles) ==========
  let resizing = false, resizeDir = '', resizeStartX, resizeStartY, resizeStartRect;
  if(!cloudMode){
    bubble.querySelectorAll('.bwResize').forEach(handle => {
      handle.addEventListener('mousedown', e => {
        resizing = true;
        resizeDir = handle.className.replace('bwResize bwResize--','');
        resizeStartX = e.clientX; resizeStartY = e.clientY;
        resizeStartRect = bubble.getBoundingClientRect();
        bubble.classList.add('bw-resizing');
        e.preventDefault(); e.stopPropagation();
      });
    });
    document.addEventListener('mousemove', e => {
      if(!resizing) return;
      const dx = e.clientX - resizeStartX;
      const dy = e.clientY - resizeStartY;
      const r = resizeStartRect;
      let newL = r.left, newT = r.top, newW = r.width, newH = r.height;
      if(resizeDir.includes('e')) newW = r.width + dx;
      if(resizeDir.includes('w')){ newW = r.width - dx; newL = r.left + dx; }
      if(resizeDir.includes('s')) newH = r.height + dy;
      if(resizeDir.includes('n')){ newH = r.height - dy; newT = r.top + dy; }
      newW = Math.max(260, Math.min(window.innerWidth - newL, newW));
      newH = Math.max(200, Math.min(window.innerHeight - newT, newH));
      if(resizeDir.includes('w')) newL = r.left + r.width - newW;
      if(resizeDir.includes('n')) newT = r.top + r.height - newH;
      bubble.style.width = newW + 'px';
      bubble.style.height = newH + 'px';
      bubble.style.left = Math.max(0, newL) + 'px';
      bubble.style.top = Math.max(0, newT) + 'px';
    });
    document.addEventListener('mouseup', () => {
      if(!resizing) return;
      resizing = false;
      bubble.classList.remove('bw-resizing');
      localStorage.setItem(BUBBLE_SIZE_KEY, JSON.stringify({w:parseInt(bubble.style.width), h:parseInt(bubble.style.height)}));
      localStorage.setItem(BUBBLE_POS_KEY, JSON.stringify({left:parseInt(bubble.style.left), top:parseInt(bubble.style.top)}));
    });
  }

  // ========== Send Message ==========
  async function sendMessage(){
    const text = inputEl.value.trim();
    if(!text && !bwPendingAttachments.length) return;
    const buddyReplyBaseline = latestBuddyFingerprint(messages);
    const clientNonce = 'bw-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
    inputEl.value = '';
    // Upload attachments if any
    const uploaded = await bwUploadAttachments();
    const displayText = text + (uploaded.length ? '\n[' + uploaded.map(f => f.original_name || f.filename).join(', ') + ']' : '');
    const msgMeta = { client_nonce: clientNonce };
    if(uploaded.length) msgMeta.attachments = uploaded;
    addMessage({from:'user', to:'buddy', content:displayText, timestamp:new Date().toISOString(), meta: msgMeta});
    widget.classList.add('thinking');
    try {
      const payload = {from:'user', to:'buddy', content:text, meta: msgMeta};
      await bridgeFetch(API + '/send', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      });
      refreshBuddyPresence();
      await waitForBuddyReply(buddyReplyBaseline);
    } catch(e){ console.error('Buddy widget send failed:', e); }
  }

  sendBtn.addEventListener('click', sendMessage);
  inputEl.addEventListener('keydown', e => {
    if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); sendMessage(); }
  });

  // ========== Attachment System (Ctrl+V paste + click attach) ==========
  const bwPendingAttachments = [];
  const bwAttachPreviewEl = document.getElementById('bwAttachPreview');

  function bwRenderAttachPreview(){
    bwAttachPreviewEl.innerHTML = '';
    if(bwPendingAttachments.length === 0){
      bwAttachPreviewEl.classList.remove('has-items');
      return;
    }
    bwAttachPreviewEl.classList.add('has-items');
    bwPendingAttachments.forEach((att, idx) => {
      const item = document.createElement('div');
      item.className = 'bwAttachPreview__item' + (att.isImage ? '' : ' bwAttachPreview__item--file');
      if(att.isImage){
        const img = document.createElement('img');
        if(att.dataUrl) img.src = att.dataUrl;
        img.alt = att.file.name;
        item.appendChild(img);
      } else {
        const ext = att.file.name.split('.').pop().toUpperCase();
        item.textContent = ext || 'FILE';
      }
      const rm = document.createElement('button');
      rm.className = 'bwAttachPreview__remove';
      rm.textContent = '\u00d7';
      rm.title = 'Entfernen';
      rm.addEventListener('click', () => {
        bwPendingAttachments.splice(idx, 1);
        bwRenderAttachPreview();
      });
      item.appendChild(rm);
      bwAttachPreviewEl.appendChild(item);
    });
  }

  function bwAddAttachment(file){
    const isImage = file.type.startsWith('image/');
    const att = { file, isImage, dataUrl: null };
    if(isImage){
      const reader = new FileReader();
      reader.onload = () => { att.dataUrl = reader.result; bwRenderAttachPreview(); };
      reader.readAsDataURL(file);
    }
    bwPendingAttachments.push(att);
    bwRenderAttachPreview();
  }

  async function bwUploadAttachments(){
    if(bwPendingAttachments.length === 0) return [];
    const form = new FormData();
    bwPendingAttachments.forEach(att => form.append('files', att.file, att.file.name));
    try {
      const res = await bridgeFetch(API + '/chat/upload', { method: 'POST', body: form, signal: AbortSignal.timeout(10000) });
      const data = await res.json();
      if(data.ok && data.files && data.files.length > 0){
        bwPendingAttachments.length = 0;
        bwRenderAttachPreview();
        return data.files;
      }
    } catch(e){ console.error('Buddy widget upload failed:', e); }
    return [];
  }

  // Ctrl+V paste handler
  inputEl.addEventListener('paste', e => {
    const items = e.clipboardData && e.clipboardData.items;
    if(!items) return;
    for(let i = 0; i < items.length; i++){
      const item = items[i];
      if(item.kind === 'file'){
        e.preventDefault();
        const file = item.getAsFile();
        if(file) bwAddAttachment(file);
      }
    }
  });

  // Click attach button
  attachBtn.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    const files = Array.from(fileInput.files || []);
    files.forEach(file => bwAddAttachment(file));
    fileInput.value = '';
  });

  // ========== Load History ==========
  async function fetchBuddyHistory(){
    try {
      const res = await bridgeFetch(API + '/history?limit=500', {signal: AbortSignal.timeout(5000)});
      if(!res.ok) return null;
      const data = await res.json();
      return (data.messages || []).filter(m =>
        (m.from === 'buddy' && m.to === 'user') || (m.from === 'user' && m.to === 'buddy')
      ).filter(isBuddyWidgetVisibleMessage);
    } catch(e){ return null; }
  }

  async function loadHistory(){
    const hist = await fetchBuddyHistory();
    if(!hist) return;
    messages = mergeBuddyMessages(messages, hist);
    renderMessages();
  }

  async function waitForBuddyReply(baselineFingerprint){
    for(let attempt = 0; attempt < 15; attempt += 1){
      await new Promise(resolve => setTimeout(resolve, 2000));
      const hist = await fetchBuddyHistory();
      if(!hist) continue;
      messages = mergeBuddyMessages(messages, hist);
      renderMessages();
      if(latestBuddyFingerprint(hist) && latestBuddyFingerprint(hist) !== baselineFingerprint){
        widget.classList.remove('thinking');
        return true;
      }
    }
    widget.classList.remove('thinking');
    return false;
  }

  // ========== WebSocket ==========
  let ws = null;
  let _bwHasConnectedOnce = false;
  let _bwWsRetry = 1000;

  function connectWS(){
    try { ws = new WebSocket(buildBridgeWsUrl(WS_URL)); } catch(e){ return; }
    ws.onopen = () => {
      _bwHasConnectedOnce = true;
      _bwWsRetry = 1000;
      ws.send(JSON.stringify({type:'subscribe', agent_id:'buddy_widget_listener'}));
      // UI-role WebSocket subscribe does not deliver history. Re-sync on every
      // successful connect so messages are recovered across startup and
      // reconnect gaps.
      loadHistory();
    };
    ws.onmessage = evt => {
      try {
        const data = JSON.parse(evt.data);
        if(data.type === 'message'){
          const m = data.message || data;
          const isBuddyMsg = (m.from === 'buddy' && (m.to === 'user' || m.to === 'all'));
          if(!isBuddyMsg) return;
          if(!isBuddyWidgetVisibleMessage(m)) return;
          addMessage({from:m.from, to:m.to, content:m.content, timestamp:m.timestamp || new Date().toISOString(), id:m.id});
          widget.classList.remove('thinking');
          if(!bubbleOpen && BUDDY_WIDGET_CONFIG.openOnIncoming){
            openBubble();
          } else {
            renderMessages();
          }
        }
      } catch(e){}
    };
    ws.onclose = () => { setTimeout(connectWS, _bwWsRetry); _bwWsRetry = Math.min(_bwWsRetry * 2, 30000); };
    ws.onerror = () => { try { ws.close(); } catch(e){} };
  }

  // ========== First-Time CLI Detection ==========
  async function firstTimeCheck(){
    if(localStorage.getItem(SEEN_KEY)) return;
    localStorage.setItem(SEEN_KEY, '1');
    try {
      const res = await bridgeFetch(API + '/cli/detect?skip_runtime=1', {signal: AbortSignal.timeout(3000)});
      if(res.ok){
        const data = await res.json();
        const tools = Array.isArray(data?.cli?.available)
          ? data.cli.available
          : Object.entries(data.tools || {}).filter(([,v]) => v).map(([k]) => k);
        if(tools.length > 0){
          addMessage({from:'buddy', to:'user', content:'Ich sehe ' + tools.join(', ') + ' ist installiert. Bereit loszulegen?', timestamp:new Date().toISOString()});
          if(BUDDY_WIDGET_CONFIG.autoOpenOnInit) openBubble();
          return;
        }
      }
    } catch(e){}
    const lang = (navigator.language || 'de').slice(0,2);
    const greet = lang === 'de' ? 'Hallo! Ich bin Buddy, dein Concierge. Wie kann ich helfen?'
      : lang === 'fr' ? 'Salut! Je suis Buddy, ton concierge. Comment puis-je aider?'
      : lang === 'es' ? 'Hola! Soy Buddy, tu concierge. Como puedo ayudar?'
      : "Hi! I'm Buddy, your concierge. How can I help?";
    addMessage({from:'buddy', to:'user', content:greet, timestamp:new Date().toISOString()});
    if(BUDDY_WIDGET_CONFIG.autoOpenOnInit) openBubble();
  }

  // ========== Init ==========
  loadHistory().then(() => {
    refreshBuddyPresence();
    firstTimeCheck();
    connectWS();
  });
  setInterval(refreshBuddyPresence, 15000);
})();
