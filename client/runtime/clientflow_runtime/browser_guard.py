#!/usr/bin/env python3
"""
ClientFlow V2 Browser Guard (ported from verified legacy Browser Guard)

Defensiv ClientFlow Browser Guard via Chrome Remote Debugging Protocol.

Rettet efter v1.1-log:
- Main page WebSocket kunne lukke med "no close frame received or sent"
- Cookie Information iframe-target kunne afvise WebSocket med HTTP 500
- Derfor:
  * Vi skipper iframe-/worker-targets og policy.app.cookieinformation.com
  * Vi evaluerer kun i hovedsider af type "page"
  * Vi bruger små, hurtige Runtime.evaluate-kald
  * Vi skjuler cookie overlay via CSS/DOM først; vi klikker ikke som primær handling
  * Kort timeout pr. WebSocket-kald
"""

import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

try:
    import websockets
except Exception as e:
    print(f"FEJL: Python-modulet websockets mangler: {e}", file=sys.stderr)
    sys.exit(1)


LOADED_ENV_FILE_VALUES = {}

# v1.5.9:
# Browser Guard læser ikke længere /etc/clientflow/clientflow.env direkte.
# Den fil kan indeholde secrets og bør ikke læses af denne service.
# Brug i stedet systemd drop-in:
# /etc/systemd/system/clientflow_browser_guard.service.d/10-browser-guard-env.conf

HOST = os.environ.get("CLIENTFLOW_CHROME_DEBUG_HOST", "127.0.0.1")
PORT = int(os.environ.get("CLIENTFLOW_CHROME_DEBUG_PORT", "9222"))
INTERVAL = float(os.environ.get("CLIENTFLOW_BROWSER_GUARD_INTERVAL", "2"))
DEFAULT_REFRESH_SEC = int(os.environ.get("CLIENTFLOW_BROWSER_GUARD_REFRESH_SEC", "900"))
ENABLE_REFRESH = os.environ.get("CLIENTFLOW_BROWSER_GUARD_ENABLE_REFRESH", "1").strip().lower() in ("1", "true", "yes", "y")
REFRESH_MIN_SEC = int(os.environ.get("CLIENTFLOW_BROWSER_GUARD_REFRESH_MIN_SEC", "60"))
REFRESH_MAX_SEC = int(os.environ.get("CLIENTFLOW_BROWSER_GUARD_REFRESH_MAX_SEC", "86400"))
CONFIG_PATH = Path(os.environ.get("CLIENTFLOW_DISPLAY_CONFIG_PATH", "/var/lib/clientflow/display-runtime/configuration.json"))
WS_TIMEOUT = float(os.environ.get("CLIENTFLOW_BROWSER_GUARD_WS_TIMEOUT", "4"))

# v1.4.1: Guard må ikke forstyrre første sidelæsning.
# Vent til siden er complete + lidt ekstra stabil tid, før CSS/DOM-regler kører.
START_DELAY_SEC = int(os.environ.get("CLIENTFLOW_BROWSER_GUARD_START_DELAY_SEC", "1"))

# Cookie-håndtering:
#   off    = gør ingenting
#   hide   = skjul kendte cookie/consent overlays
#   accept = forsøg først at klikke "Accepter alle"; fallback til hide
#
# Backward compatibility:
# Hvis CLIENTFLOW_BROWSER_GUARD_COOKIE_MODE ikke er sat, bruges hide/off ud fra
# den gamle CLIENTFLOW_BROWSER_GUARD_ENABLE_COOKIE_HIDE.
ENABLE_COOKIE_HIDE = os.environ.get("CLIENTFLOW_BROWSER_GUARD_ENABLE_COOKIE_HIDE", "1").strip().lower() in ("1", "true", "yes", "y")
COOKIE_MODE = os.environ.get("CLIENTFLOW_BROWSER_GUARD_COOKIE_MODE", "").strip().lower()
if COOKIE_MODE not in ("off", "hide", "accept"):
    COOKIE_MODE = "hide" if ENABLE_COOKIE_HIDE else "off"

ENABLE_AGGRESSIVE_HIDE = os.environ.get("CLIENTFLOW_BROWSER_GUARD_ENABLE_AGGRESSIVE_HIDE", "1").strip().lower() in ("1", "true", "yes", "y")

# At override window.open/alert/confirm kan påvirke enkelte sites. Derfor default off.
ENABLE_NATIVE_BLOCK = os.environ.get("CLIENTFLOW_BROWSER_GUARD_ENABLE_NATIVE_BLOCK", "1").strip().lower() in ("1", "true", "yes", "y")

VERSION = "1.6.5"

DEBUG_URL = f"http://{HOST}:{PORT}/json"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def log(msg: str) -> None:
    print(f"{now_iso()} - browser_guard: {msg}", flush=True)


UNREADY_LOG_INTERVAL_SEC = int(os.environ.get("CLIENTFLOW_BROWSER_GUARD_UNREADY_LOG_INTERVAL_SEC", "60"))
EMPTY_SUMMARY_INTERVAL_SEC = int(os.environ.get("CLIENTFLOW_BROWSER_GUARD_EMPTY_SUMMARY_INTERVAL_SEC", "60"))
# Golden default: Chrome may be intentionally closed while Browser Guard runs.
# In that state, DevTools/9222 refuses connections every poll. Do not log that
# normal state unless explicitly enabled for debugging.
LOG_CHROME_UNREADY = os.environ.get("CLIENTFLOW_BROWSER_GUARD_LOG_CHROME_UNREADY", "0").strip().lower() in ("1", "true", "yes", "y")
_LAST_CHROME_UNREADY_LOG = 0.0
_LAST_CHROME_UNREADY_MESSAGE = ""
_SUPPRESSED_CHROME_UNREADY_LOGS = 0


def log_chrome_debug_unready(detail: str) -> None:
    """Handle normal Chrome-closed/DevTools-not-ready state quietly.

    Browser Guard may run while kiosk Chrome is intentionally closed. In that
    normal state, 127.0.0.1:9222 refuses connections every poll. For Golden
    clients this must not create journal spam. Set
    CLIENTFLOW_BROWSER_GUARD_LOG_CHROME_UNREADY=1 temporarily when debugging.
    """
    global _LAST_CHROME_UNREADY_LOG, _LAST_CHROME_UNREADY_MESSAGE, _SUPPRESSED_CHROME_UNREADY_LOGS
    detail = str(detail or "ukendt fejl")

    if not LOG_CHROME_UNREADY:
        _SUPPRESSED_CHROME_UNREADY_LOGS += 1
        return

    now = time.monotonic()
    interval = max(10, int(UNREADY_LOG_INTERVAL_SEC or 60))
    should_log = (detail != _LAST_CHROME_UNREADY_MESSAGE) or (now - _LAST_CHROME_UNREADY_LOG >= interval)
    if should_log:
        suffix = ""
        if _SUPPRESSED_CHROME_UNREADY_LOGS:
            suffix = f"; undertrykte gentagelser={_SUPPRESSED_CHROME_UNREADY_LOGS}"
        log(f"Chrome remote debugging ikke klar på {DEBUG_URL}: {detail}{suffix}")
        _LAST_CHROME_UNREADY_LOG = now
        _LAST_CHROME_UNREADY_MESSAGE = detail
        _SUPPRESSED_CHROME_UNREADY_LOGS = 0
    else:
        _SUPPRESSED_CHROME_UNREADY_LOGS += 1


def _coerce_refresh_sec(value, fallback=DEFAULT_REFRESH_SEC) -> int:
    if not ENABLE_REFRESH:
        return 0
    if value is None or str(value).strip() == "":
        value = fallback
    try:
        seconds = int(float(str(value).strip()))
    except Exception:
        seconds = int(fallback or 0)
    if seconds <= 0:
        return 0
    return max(REFRESH_MIN_SEC, min(REFRESH_MAX_SEC, seconds))


def get_refresh_sec() -> int:
    """Læs backend-styret refresh-interval fra clientflow_config.json.

    0 deaktiverer auto-refresh. Hvis feltet mangler, bruges environment/default 900s.
    """
    if not ENABLE_REFRESH:
        return 0
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "browser_refresh_interval_sec" in data:
                return _coerce_refresh_sec(data.get("browser_refresh_interval_sec"))
    except Exception as e:
        log(f"Kunne ikke læse browser refresh-interval fra {CONFIG_PATH}: {e}")
    return _coerce_refresh_sec(DEFAULT_REFRESH_SEC)


def get_tabs():
    try:
        with urllib.request.urlopen(DEBUG_URL, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        log_chrome_debug_unready(str(e))
        return []


def is_main_page_target(tab: dict) -> bool:
    url = tab.get("url", "") or ""
    target_type = tab.get("type", "") or ""

    # v1.6.2:
    # Evaluer kun rigtige hovedsider. CookieInformation eksponerer også et
    # cross-origin iframe-target via DevTools; det kan afvise WebSocket med
    # HTTP 500 og må ikke behandles som en refresh-/guard-side.
    if target_type and target_type != "page":
        return False

    if not url.startswith(("http://", "https://")):
        return False

    blocked = [
        "chrome-extension://",
        "devtools://",
        "policy.app.cookieinformation.com",
        "cookiesharingiframe",
    ]

    if any(b in url for b in blocked):
        return False

    return True


HIDE_JS = r"""
(() => {
  const VERSION = '1.6.2';

  function safe(fn, fallback) {
    try { return fn(); } catch (e) { return fallback; }
  }

  const START_DELAY_SEC = __START_DELAY_SEC__;
  const COOKIE_MODE = '__COOKIE_MODE__';
  const ENABLE_AGGRESSIVE_HIDE = __ENABLE_AGGRESSIVE_HIDE__;
  const ENABLE_NATIVE_BLOCK = __ENABLE_NATIVE_BLOCK__;
  const IS_KIOSK_REFRESH = safe(() => new URL(location.href).searchParams.has('_kiosk_refresh'), false);

  // v1.5.2:
  // Accept-mode må gerne forsøge at klikke cookie-knappen før readyState=complete,
  // fordi cookie-/consent-dialoger på nogle sites kan blokere eller forsinke complete.
  // Hide/CSS-regler venter stadig til complete, så vi ikke forstyrrer første load.
  if (!document.body) {
    return { version: VERSION, href: location.href, readyState: document.readyState, skipped: 'no-body', cookieMode: COOKIE_MODE };
  }

  if (window.__clientflowBrowserGuardHref !== location.href) {
    window.__clientflowBrowserGuardHref = location.href;
    window.__clientflowBrowserGuardStableAt = Date.now();
    window.__clientflowBrowserGuardHideLoop = false;
  }

  window.__clientflowBrowserGuardStableAt = window.__clientflowBrowserGuardStableAt || Date.now();
  const stableFor = Math.floor((Date.now() - window.__clientflowBrowserGuardStableAt) / 1000);
  if (stableFor < START_DELAY_SEC) {
    return { version: VERSION, href: location.href, readyState: document.readyState, skipped: 'start-delay', cookieMode: COOKIE_MODE, stableFor, startDelaySec: START_DELAY_SEC };
  }

  if (COOKIE_MODE === 'off') {
    document.documentElement.setAttribute('data-clientflow-browser-guard', VERSION);
    return { version: VERSION, href: location.href, readyState: document.readyState, skipped: 'cookie-mode-off', cookieMode: COOKIE_MODE, stableFor };
  }

  var acceptResult = null;

  if (COOKIE_MODE === 'accept') {
    acceptResult = tryAcceptCookies();
    if (acceptResult && acceptResult.clicked) {
      // v1.6.2:
      // Ved almindelig URL change må dialogen gerne være synlig kortvarigt.
      // Efter kiosk auto-refresh (_kiosk_refresh) må den ikke stå tilbage.
      // Derfor skjuler vi kun aggressivt i accept-mode, når det er et
      // tidsstyret refresh, ikke ved første URL change.
      let hiddenAfterAccept = 0;
      if (IS_KIOSK_REFRESH && document.readyState === 'complete') {
        ensureHideLoop();
        hiddenAfterAccept = hideKnown();
      } else {
        restorePage();
      }
      return {
        version: VERSION,
        href: location.href,
        readyState: document.readyState,
        cookieMode: COOKIE_MODE,
        accepted: true,
        acceptResult,
        stableFor,
        hidden: hiddenAfterAccept,
        overlay: document.querySelector('#coiOverlay') ? 'present' : null,
        css: !!document.getElementById('clientflow-browser-guard-css')
      };
    }
  }

  if (document.readyState !== 'complete') {
    return {
      version: VERSION,
      href: location.href,
      readyState: document.readyState,
      skipped: 'waiting-for-complete-after-accept-check',
      cookieMode: COOKIE_MODE,
      accepted: false,
      acceptResult,
      stableFor
    };
  }

  function isVisible(el) {
    return safe(() => {
      if (!el) return false;
      const s = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return s.display !== 'none' &&
             s.visibility !== 'hidden' &&
             s.opacity !== '0' &&
             r.width > 10 &&
             r.height > 10;
    }, false);
  }

  function buttonText(el) {
    return safe(() => [
      el.innerText || '',
      el.textContent || '',
      el.getAttribute('aria-label') || '',
      el.getAttribute('title') || '',
      el.id || '',
      el.className || '',
      el.value || ''
    ].join(' ').replace(/\s+/g, ' ').trim(), '');
  }

  function tryAcceptCookies() {
    // Fjern eventuel gammel guard-CSS først. Tidligere hide-mode kan have
    // skjult #coiOverlay, så knappen ikke længere er "visible".
    safe(() => {
      const oldCss = document.getElementById('clientflow-browser-guard-css');
      if (oldCss) oldCss.remove();
    });
    restorePage();

    const successKey = '__clientflowCookieAcceptSuccess:' + location.href;
    const attemptsKey = '__clientflowCookieAcceptAttempts:' + location.href;
    window[attemptsKey] = (window[attemptsKey] || 0) + 1;

    // v1.6.0:
    // Lås kun efter faktisk succes. Mislykkede forsøg må gerne prøves igen.
    // Når accept allerede er lykkedes på samme URL, returnerer vi accepted=True,
    // så vi undgår at kalde Cookie Information API hvert loop.
    if (window[successKey]) {
      return { clicked: true, method: 'already-accepted-this-url', alreadyAccepted: true, attempts: window[attemptsKey] };
    }

    const rejectRe = /afvis|reject|decline|deny|kun nødvendige|only necessary|necessary only|nødvendige cookies|essential only|settings|indstillinger|tilpas|customize|manage|præferencer|preferences/i;

    function forceShowForClick(el) {
      safe(() => {
        let node = el;
        let depth = 0;
        while (node && node.nodeType === 1 && depth < 8) {
          const id = node.id || '';
          const cls = String(node.className || '');
          if (/coi|cookie|consent|banner|overlay/i.test(id + ' ' + cls)) {
            node.style.setProperty('display', 'block', 'important');
            node.style.setProperty('visibility', 'visible', 'important');
            node.style.setProperty('opacity', '1', 'important');
            node.style.setProperty('pointer-events', 'auto', 'important');
          }
          node = node.parentElement;
          depth += 1;
        }
        el.style.setProperty('visibility', 'visible', 'important');
        el.style.setProperty('opacity', '1', 'important');
        el.style.setProperty('pointer-events', 'auto', 'important');
      });
    }

    function robustClick(el) {
      return safe(() => {
        if (!el) return false;
        forceShowForClick(el);
        try { el.scrollIntoView({ block: 'center', inline: 'center' }); } catch (_) {}

        const opts = { bubbles: true, cancelable: true, view: window };
        ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach((type) => {
          try {
            const ev = type.startsWith('pointer')
              ? new PointerEvent(type, { ...opts, pointerId: 1, pointerType: 'mouse', isPrimary: true })
              : new MouseEvent(type, opts);
            el.dispatchEvent(ev);
          } catch (_) {
            try { el.dispatchEvent(new MouseEvent(type, opts)); } catch (__) {}
          }
        });

        try { el.click(); } catch (_) {}
        return true;
      }, false);
    }

    // Cookie Information API-forsøg. Forskellige versioner eksponerer forskellige metoder.
    const apiResult = safe(() => {
      const ci = window.CookieInformation || window.CookieConsent || null;
      if (!ci) return null;

      const methods = [
        'submitAllCategories',
        'acceptAllCategories',
        'acceptAll',
        'allowAll',
        'submitConsent'
      ];

      for (const name of methods) {
        if (typeof ci[name] === 'function') {
          try {
            ci[name]();
            window[successKey] = true;
            return { clicked: true, method: 'cookie-information-api', api: name, attempts: window[attemptsKey] };
          } catch (_) {}
        }
      }

      return { clicked: false, method: 'cookie-information-api', reason: 'no-known-api-methods', keys: Object.keys(ci).slice(0, 30) };
    }, null);

    if (apiResult && apiResult.clicked) return apiResult;

    // Direkte Cookie Information / CMP selectors.
    // Her kræver vi ikke isVisible, fordi gammel CSS kan have skjult overlayet.
    const directAcceptSelectors = [
      '#coiOverlay .coi-banner__accept',
      '#coiConsentBanner .coi-banner__accept',
      '#coi-banner-wrapper .coi-banner__accept',
      '#coiOverlay button[aria-label*="accept" i]',
      '#coiOverlay button[aria-label*="accepter" i]',
      '#coiOverlay button[aria-label*="tillad" i]',
      '#coiOverlay [data-consent="all"]',
      '#coiOverlay [data-consent*="all" i]',
      '#coiOverlay button.coi-banner__accept',
      '#coi-banner-wrapper button.coi-banner__accept',
      'button.coi-banner__accept',
      'button[class*="coi"][class*="accept" i]',
      '[id*="coi" i] button[class*="accept" i]',
      '[id*="coi" i] [role="button"][class*="accept" i]',
      '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
      '#onetrust-accept-btn-handler',
      '[data-testid*="accept" i]',
      '[data-cy*="accept" i]',
      '[aria-label*="Accepter alle" i]',
      '[aria-label*="Accept all" i]',
      '[aria-label*="Tillad alle" i]',
      '[id*="accept-all" i]',
      '[class*="accept-all" i]'
    ];

    for (const sel of directAcceptSelectors) {
      const direct = safe(() => Array.from(document.querySelectorAll(sel)), [])
        .filter((el) => !rejectRe.test(buttonText(el)));
      if (direct.length > 0) {
        const el = direct[0];
        const text = buttonText(el);
        if (robustClick(el)) {
          window[successKey] = true;
          return { clicked: true, method: 'direct-selector', selector: sel, text, attempts: window[attemptsKey], apiResult };
        }
      }
    }

    // Cookie Information overlay fallback: find accept/all-knap i roden.
    const coiRoots = safe(() => Array.from(document.querySelectorAll(
      '#coiOverlay, #coiConsentBanner, #coi-banner-wrapper, [id*="coi" i], [class*="coi-banner" i]'
    )), []);

    for (const root of coiRoots) {
      const rootButtons = safe(() => Array.from(root.querySelectorAll('button, [role="button"], a, input[type="button"], input[type="submit"]')), [])
        .map((el) => ({ el, text: buttonText(el) }))
        .filter((x) => !rejectRe.test(x.text));

      const preferred =
        rootButtons.find((x) => /accepter alle|acceptér alle|accept all|tillad alle|godkend alle|alle cookies|all cookies/i.test(x.text)) ||
        rootButtons.find((x) => /accept|accepter|acceptér|tillad|godkend|ok|okay/i.test(x.text)) ||
        rootButtons[rootButtons.length - 1];

      if (preferred && preferred.el && robustClick(preferred.el)) {
        window[successKey] = true;
        return {
          clicked: true,
          method: 'coi-root-fallback',
          text: preferred.text,
          buttonCount: rootButtons.length,
          attempts: window[attemptsKey],
          apiResult
        };
      }
    }

    // Generisk synlig tekst-match.
    const strongAcceptRe = /^(accepter alle|accepter alle cookies|acceptér alle|acceptér alle cookies|accept all|accept all cookies|allow all|allow all cookies|tillad alle|tillad alle cookies|godkend alle|godkend alle cookies|agree to all|i accept all|i agree to all|alle cookies)$/i;
    const mediumAcceptRe = /^(accepter|acceptér|accept|allow|tillad|godkend|ok|okay|enig|jeg accepterer|i agree|i accept|got it|forstået)$/i;
    const looseAcceptRe = /\b(accepter alle|accepter alle cookies|acceptér alle|acceptér alle cookies|accept all|accept all cookies|allow all|allow all cookies|tillad alle|tillad alle cookies|godkend alle|godkend alle cookies|alle cookies)\b/i;

    const selectors = [
      'button',
      'a[role="button"]',
      '[role="button"]',
      'input[type="button"]',
      'input[type="submit"]',
      '[data-testid*="accept" i]',
      '[data-cy*="accept" i]',
      '[id*="accept" i]',
      '[class*="accept" i]',
      '[id*="allow" i]',
      '[class*="allow" i]',
      '[aria-label*="accept" i]',
      '[aria-label*="accepter" i]',
      '[aria-label*="tillad" i]'
    ];

    function collectCandidateElements() {
      const found = [];
      const seen = new Set();

      function add(el) {
        if (!el || seen.has(el)) return;
        seen.add(el);
        found.push(el);
      }

      function walk(root, depth = 0) {
        if (!root || depth > 4) return;
        safe(() => Array.from(root.querySelectorAll(selectors.join(','))).forEach(add));
        safe(() => {
          Array.from(root.querySelectorAll('*')).forEach((el) => {
            if (el.shadowRoot) walk(el.shadowRoot, depth + 1);
          });
        });
      }

      walk(document);
      return found;
    }

    const candidates = safe(() => collectCandidateElements(), [])
      .filter(isVisible)
      .map((el) => ({ el, text: buttonText(el) }))
      .filter((x) => x.text && !rejectRe.test(x.text));

    const rank = (x) => {
      const t = x.text.trim();
      if (strongAcceptRe.test(t)) return 100;
      if (looseAcceptRe.test(t)) return 80;
      if (mediumAcceptRe.test(t)) return 60;
      if (/accept|accepter|acceptér|allow|tillad|godkend/i.test(t)) return 40;
      return 0;
    };

    const best = candidates
      .map((x) => ({ ...x, score: rank(x) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)[0];

    if (!best) {
      return {
        clicked: false,
        reason: 'no-accept-button',
        attempts: window[attemptsKey],
        apiResult,
        candidates: candidates.slice(0, 8).map(x => x.text).filter(Boolean),
        coiRoots: safe(() => Array.from(document.querySelectorAll('#coiOverlay, #coiConsentBanner, #coi-banner-wrapper, [id*="coi" i], [class*="coi" i]')).slice(0, 8).map(el => ({
          tag: el.tagName,
          id: el.id || '',
          cls: String(el.className || '').slice(0, 120),
          text: String(el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 180)
        })), [])
      };
    }

    if (!robustClick(best.el)) {
      return { clicked: false, reason: 'robust-click-failed', text: best.text, score: best.score, attempts: window[attemptsKey], apiResult };
    }

    window[successKey] = true;
    return { clicked: true, method: 'text-rank', text: best.text, score: best.score, attempts: window[attemptsKey], apiResult };
  }

  function addCss() {
    if (document.getElementById('clientflow-browser-guard-css')) return true;

    const css = document.createElement('style');
    css.id = 'clientflow-browser-guard-css';
    css.textContent = `
      #coiOverlay,
      #coiConsentBanner,
      #coi-banner-wrapper,
      #coiPage-1,
      #coiPage-2,
      .coi-overlay,
      .coi-banner__wrapper,
      .coi-banner__page,
      .coi-banner__summary,
      [class*="coi-banner" i],
      [id^="coi" i],
      [class^="coi" i],
      [class*=" coi" i],
      #CybotCookiebotDialog,
      #CybotCookiebotDialogBodyUnderlay,
      #CookiebotWidget,
      [id^="CybotCookiebot" i],
      [class*="CybotCookiebot" i],
      #usercentrics-root,
      [data-testid="uc-app-container"],
      [data-testid="uc-overlay"],
      #onetrust-banner-sdk,
      #onetrust-consent-sdk,
      .didomi-popup-container,
      .didomi-consent-popup,
      .qc-cmp2-container,
      .cc-window,
      .cookie-banner,
      .cookie-consent,
      .cookie-box,
      .cookie-notice,
      .consent-banner,
      .consent-modal,
      .CookieConsent,
      .cookiescript_injected,
      iframe[src*="cookieinformation" i],
      iframe[src*="cookiesharingiframe" i],
      iframe[title*="cookie" i],
      iframe[src*="policy.app.cookieinformation.com" i],
      iframe[src*="cookiesharingiframe" i],
      iframe[title*="cookie" i],
      iframe[id*="cookie" i],
      iframe[class*="cookie" i],
      iframe[id*="coi" i],
      iframe[class*="coi" i],
      [data-clientflow-browser-guard-hidden] {
        display: none !important;
        visibility: hidden !important;
        pointer-events: none !important;
        opacity: 0 !important;
      }

      #tm-kiosk-bar,
      #tm-kiosk-text {
        pointer-events: none !important;
        z-index: 2147483647 !important;
      }

      :fullscreen #tm-kiosk-bar,
      :fullscreen #tm-kiosk-text,
      :-webkit-full-screen #tm-kiosk-bar,
      :-webkit-full-screen #tm-kiosk-text {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
      }
    `;

    return safe(() => {
      (document.head || document.documentElement).appendChild(css);
      return true;
    }, false);
  }

  function hide(el, reason) {
    if (!el) return false;
    if (el.id === 'tm-kiosk-bar' || el.id === 'tm-kiosk-text' || el.id === 'clientflow-browser-guard-css') return false;

    safe(() => el.setAttribute('data-clientflow-browser-guard-hidden', reason || 'hidden'));
    safe(() => el.style.setProperty('display', 'none', 'important'));
    safe(() => el.style.setProperty('visibility', 'hidden', 'important'));
    safe(() => el.style.setProperty('pointer-events', 'none', 'important'));
    safe(() => el.style.setProperty('opacity', '0', 'important'));
    return true;
  }

  function restorePage() {
    safe(() => document.documentElement.style.setProperty('overflow', 'auto', 'important'));
    safe(() => document.body && document.body.style.setProperty('overflow', 'auto', 'important'));
    safe(() => document.documentElement.style.setProperty('pointer-events', 'auto', 'important'));
    safe(() => document.body && document.body.style.setProperty('pointer-events', 'auto', 'important'));

    ['noScroll','modal-open','no-scroll','noscroll','cookie-open','coi-banner-open','coi-modal-open'].forEach(c => {
      safe(() => document.documentElement.classList.remove(c));
      safe(() => document.body && document.body.classList.remove(c));
    });
  }

  function hideKnown() {
    let hidden = 0;
    const selectors = [
      '#coiOverlay',
      '#coiConsentBanner',
      '#coi-banner-wrapper',
      '#coiPage-1',
      '#coiPage-2',
      '.coi-overlay',
      '.coi-banner__wrapper',
      '.coi-banner__page',
      '.coi-banner__summary',
      '[class*="coi-banner" i]',
      '[id^="coi" i]',
      '[class^="coi" i]',
      '[class*=" coi" i]',
      'iframe[src*="policy.app.cookieinformation.com" i]',
      'iframe[src*="cookiesharingiframe" i]',
      'iframe[title*="cookie" i]',
      'iframe[id*="cookie" i]',
      'iframe[class*="cookie" i]',
      'iframe[id*="coi" i]',
      'iframe[class*="coi" i]',
      '#CybotCookiebotDialog',
      '#CybotCookiebotDialogBodyUnderlay',
      '#CookiebotWidget',
      '[id^="CybotCookiebot" i]',
      '[class*="CybotCookiebot" i]',
      '#usercentrics-root',
      '[data-testid="uc-app-container"]',
      '[data-testid="uc-overlay"]',
      '#onetrust-banner-sdk',
      '#onetrust-consent-sdk',
      '.didomi-popup-container',
      '.didomi-consent-popup',
      '.qc-cmp2-container',
      '.cc-window',
      '.cookie-banner',
      '.cookie-consent',
      '.cookie-box',
      '.cookie-notice',
      '.consent-banner',
      '.consent-modal',
      '.CookieConsent',
      '.cookiescript_injected',
      'iframe[src*="cookieinformation" i]',
      'iframe[src*="cookiesharingiframe" i]',
      'iframe[title*="cookie" i]'
    ];

    for (const sel of selectors) {
      safe(() => document.querySelectorAll(sel).forEach(el => {
        if (hide(el, 'selector:' + sel)) hidden++;
      }));
    }

    // Aggressive heuristikker kan skjule legitime loading-containere på enkelte sites.
    // Derfor er de slået fra som standard og kan aktiveres via env, hvis der er behov.
    if (ENABLE_AGGRESSIVE_HIDE) {
      const keywords = /cookie|cookies|samtykke|consent|privatliv|personoplysninger|persondata|gdpr|marketing|statistik|funktionelle|nødvendige|du bestemmer over dine data|powered by cookie information|samarbejdspartnere bruger teknologier/i;

      const nodes = safe(() => Array.from(document.querySelectorAll('div,section,aside,dialog,form')), []);
      for (const el of nodes) {
        const meta = safe(() => [
          el.id,
          el.className,
          el.getAttribute('role'),
          el.getAttribute('aria-modal'),
          el.getAttribute('aria-label'),
          el.getAttribute('title'),
          el.innerText || el.textContent || ''
        ].join(' '), '');

        if (keywords.test(meta)) {
          if (hide(el, 'keyword')) hidden++;
          continue;
        }

        const bigFixed = safe(() => {
          const s = getComputedStyle(el);
          const r = el.getBoundingClientRect();
          const area = r.width * r.height;
          const viewport = innerWidth * innerHeight;
          const z = parseInt(s.zIndex || '0', 10) || 0;
          return ['fixed','absolute','sticky'].includes(s.position) && z >= 50 && area > viewport * 0.2;
        }, false);

        if (bigFixed) {
          if (hide(el, 'big-fixed')) hidden++;
        }
      }
    }

    restorePage();
    return hidden;
  }

  function ensureHideLoop() {
    addCss();
    if (ENABLE_NATIVE_BLOCK) blockNative();

    if (!window.__clientflowBrowserGuardHideLoop) {
      window.__clientflowBrowserGuardHideLoop = true;
      safe(() => {
        new MutationObserver(() => {
          addCss();
          hideKnown();
        }).observe(document.documentElement || document.body, {
          childList: true,
          subtree: true,
          attributes: true,
          attributeFilter: ['class','style','id','role','aria-modal','aria-label','src','title']
        });
      });
      safe(() => setInterval(() => {
        document.documentElement.setAttribute('data-clientflow-browser-guard', VERSION);
        addCss();
        hideKnown();
      }, 500));
    }
  }

  function blockNative() {
    const noop = function(){};
    const yes = function(){ return true; };
    const nil = function(){ return null; };

    safe(() => { window.alert = noop; });
    safe(() => { window.confirm = yes; });
    safe(() => { window.prompt = nil; });
    safe(() => { window.print = noop; });
    safe(() => {
      window.open = function() {
        return { closed: true, close(){}, focus(){}, blur(){}, postMessage(){}, location: { href: 'about:blank' } };
      };
    });
  }

  document.documentElement.setAttribute('data-clientflow-browser-guard', VERSION);
  window.__clientflowBrowserGuardVersion = VERSION;

  var acceptResult = null;

  if (COOKIE_MODE === 'accept') {
    acceptResult = tryAcceptCookies();
    if (acceptResult && acceptResult.clicked) {
      let hiddenAfterAccept = 0;
      if (IS_KIOSK_REFRESH) {
        ensureHideLoop();
        hiddenAfterAccept = hideKnown();
      } else {
        restorePage();
      }
      return {
        version: VERSION,
        href: location.href,
        readyState: document.readyState,
        marker: document.documentElement.getAttribute('data-clientflow-browser-guard'),
        cookieMode: COOKIE_MODE,
        accepted: true,
        acceptResult,
        hidden: hiddenAfterAccept,
        overlay: document.querySelector('#coiOverlay') ? 'present' : null,
        css: !!document.getElementById('clientflow-browser-guard-css')
      };
    }

    // v1.6.2:
    // I accept-mode skjuler vi stadig ikke ved almindelig URL change, så
    // URL-change-politikken bevares. Men efter et tidsstyret kiosk-refresh
    // (_kiosk_refresh) skal en eventuel dialog/iframe fjernes visuelt, så
    // den ikke står på infoskærmen, selv hvis accept-API'en ikke finder en knap.
    if (IS_KIOSK_REFRESH) {
      ensureHideLoop();
      const hiddenAfterRefresh = hideKnown();
      return {
        version: VERSION,
        href: location.href,
        readyState: document.readyState,
        marker: document.documentElement.getAttribute('data-clientflow-browser-guard'),
        cookieMode: COOKIE_MODE,
        accepted: false,
        acceptResult,
        hidden: hiddenAfterRefresh,
        overlay: document.querySelector('#coiOverlay') ? 'present' : null,
        css: !!document.getElementById('clientflow-browser-guard-css')
      };
    }

    restorePage();
    return {
      version: VERSION,
      href: location.href,
      readyState: document.readyState,
      marker: document.documentElement.getAttribute('data-clientflow-browser-guard'),
      cookieMode: COOKIE_MODE,
      accepted: false,
      acceptResult,
      hidden: 0,
      overlay: document.querySelector('#coiOverlay') ? 'present' : null,
      css: !!document.getElementById('clientflow-browser-guard-css')
    };
  }

  ensureHideLoop();

  const hidden = hideKnown();
  const overlay = document.querySelector('#coiOverlay');

  return {
    version: VERSION,
    href: location.href,
    readyState: document.readyState,
    marker: document.documentElement.getAttribute('data-clientflow-browser-guard'),
    cookieMode: COOKIE_MODE,
    accepted: !!(acceptResult && acceptResult.clicked),
    acceptResult,
    hidden,
    overlay: overlay ? {
      display: getComputedStyle(overlay).display,
      visibility: getComputedStyle(overlay).visibility,
      opacity: getComputedStyle(overlay).opacity
    } : null,
    css: !!document.getElementById('clientflow-browser-guard-css')
  };
})()
""".replace("__START_DELAY_SEC__", str(START_DELAY_SEC)) \
   .replace("__COOKIE_MODE__", COOKIE_MODE) \
   .replace("__ENABLE_AGGRESSIVE_HIDE__", "true" if ENABLE_AGGRESSIVE_HIDE else "false") \
   .replace("__ENABLE_NATIVE_BLOCK__", "true" if ENABLE_NATIVE_BLOCK else "false")

COUNTDOWN_JS = r"""
(() => {
  const VERSION = '1.6.2';
  window.__clientflowBrowserGuardRefreshSec = __REFRESH_SEC__;
  window.__clientflowBrowserGuardStartDelaySec = __START_DELAY_SEC__;

  function safe(fn, fallback) {
    try { return fn(); } catch (e) { return fallback; }
  }

  function getRefreshSec() {
    const value = Number(window.__clientflowBrowserGuardRefreshSec || 0);
    return Number.isFinite(value) ? value : 0;
  }

  function getStartDelaySec() {
    const value = Number(window.__clientflowBrowserGuardStartDelaySec || 0);
    return Number.isFinite(value) ? value : 0;
  }

  function removeCountdown() {
    safe(() => document.getElementById('tm-kiosk-bar')?.remove());
    safe(() => document.getElementById('tm-kiosk-text')?.remove());
  }

  function isFullscreen() {
    return safe(() => {
      if (document.fullscreenElement || document.webkitFullscreenElement || document.querySelector(':fullscreen')) return true;
      const h = Math.abs(outerHeight - screen.height) <= 2 || Math.abs(innerHeight - screen.height) <= 2;
      const w = Math.abs(outerWidth - screen.width) <= 2 || Math.abs(innerWidth - screen.width) <= 2;
      if (h && w) return true;
      if (innerHeight >= screen.availHeight - 2 && innerWidth >= screen.availWidth - 2) return true;
      return false;
    }, false);
  }

  function createCountdown() {
    if (document.getElementById('tm-kiosk-bar')) return;

    const bar = document.createElement('div');
    bar.id = 'tm-kiosk-bar';
    const txt = document.createElement('div');
    txt.id = 'tm-kiosk-text';

    Object.entries({
      position:'fixed', top:'0', left:'0', height:'6px', width:'100%',
      transform:'scaleX(0)', 'transform-origin':'left center',
      background:'linear-gradient(90deg, rgba(0,150,136,.95), rgba(76,175,80,.95))',
      'z-index':'2147483647', 'pointer-events':'none', transition:'transform 0.9s linear, opacity 0.2s',
      display:'block', visibility:'visible', opacity:'1'
    }).forEach(([k,v]) => safe(() => bar.style.setProperty(k, v, 'important')));

    Object.entries({
      position:'fixed', top:'8px', right:'10px', padding:'3px 6px',
      background:'rgba(0,0,0,.6)', color:'#fff', 'font-size':'12px',
      'border-radius':'4px', 'z-index':'2147483647', 'pointer-events':'none',
      'font-family':'sans-serif', 'line-height':'1', display:'block', visibility:'visible', opacity:'1'
    }).forEach(([k,v]) => safe(() => txt.style.setProperty(k, v, 'important')));

    safe(() => (document.body || document.documentElement).appendChild(bar));
    safe(() => (document.body || document.documentElement).appendChild(txt));
  }

  function updateCountdown() {
    const REFRESH_SEC = getRefreshSec();
    const START_DELAY_SEC = getStartDelaySec();
    if (!REFRESH_SEC || REFRESH_SEC < 60) {
      removeCountdown();
      window.__clientflowBrowserGuardStart = null;
      return { disabled: true, refreshSec: REFRESH_SEC, readyState: document.readyState };
    }

    // Start først refresh-countdown når siden faktisk er færdigindlæst
    // og URL'en har været stabil i START_DELAY_SEC sekunder.
    if (document.readyState !== 'complete') {
      return { skipped: 'not-complete', refreshSec: REFRESH_SEC, readyState: document.readyState };
    }

    if (window.__clientflowBrowserGuardCountdownHref !== location.href) {
      window.__clientflowBrowserGuardCountdownHref = location.href;
      window.__clientflowBrowserGuardCountdownCompleteAt = Date.now();
      window.__clientflowBrowserGuardStart = null;
    }

    window.__clientflowBrowserGuardCountdownCompleteAt = window.__clientflowBrowserGuardCountdownCompleteAt || Date.now();
    const stableFor = Math.floor((Date.now() - window.__clientflowBrowserGuardCountdownCompleteAt) / 1000);
    if (stableFor < START_DELAY_SEC) {
      return { skipped: 'start-delay', refreshSec: REFRESH_SEC, readyState: document.readyState, stableFor, startDelaySec: START_DELAY_SEC };
    }

    createCountdown();

    if (!window.__clientflowBrowserGuardStart) window.__clientflowBrowserGuardStart = Date.now();

    const elapsed = Math.floor((Date.now() - window.__clientflowBrowserGuardStart) / 1000);
    const pct = Math.max(0, Math.min(1, elapsed / REFRESH_SEC));
    const hidden = isFullscreen();

    const bar = document.getElementById('tm-kiosk-bar');
    const txt = document.getElementById('tm-kiosk-text');

    if (bar) {
      bar.removeAttribute('data-clientflow-browser-guard-hidden');
      bar.style.setProperty('display', hidden ? 'none' : 'block', 'important');
      bar.style.setProperty('visibility', hidden ? 'hidden' : 'visible', 'important');
      bar.style.setProperty('opacity', hidden ? '0' : '1', 'important');
      bar.style.setProperty('transform', 'scaleX(' + pct + ')', 'important');
      bar.style.setProperty('z-index', '2147483647', 'important');
    }

    if (txt) {
      txt.removeAttribute('data-clientflow-browser-guard-hidden');
      const left = Math.max(0, REFRESH_SEC - elapsed);
      const m = Math.floor(left / 60);
      const s = left % 60;
      txt.textContent = 'Opdaterer om ' + m + ':' + String(s).padStart(2, '0');
      txt.style.setProperty('display', hidden ? 'none' : 'block', 'important');
      txt.style.setProperty('visibility', hidden ? 'hidden' : 'visible', 'important');
      txt.style.setProperty('opacity', hidden ? '0' : '1', 'important');
      txt.style.setProperty('z-index', '2147483647', 'important');
    }

    if (elapsed >= REFRESH_SEC) {
      window.__clientflowBrowserGuardStart = Date.now();
      const url = new URL(location.href);
      url.searchParams.set('_kiosk_refresh', Date.now().toString());
      location.replace(url.toString());
    }

    return { elapsed, hidden, bar: !!bar, text: !!txt };
  }

  if (!window.__clientflowBrowserGuardCountdownLoop) {
    window.__clientflowBrowserGuardCountdownLoop = true;
    window.__clientflowBrowserGuardStart = window.__clientflowBrowserGuardStart || Date.now();
    safe(() => setInterval(updateCountdown, 1000));
  }

  return updateCountdown();
})()
"""


async def evaluate_js(tab, js: str, label: str):
    wsurl = tab.get("webSocketDebuggerUrl")
    url = tab.get("url", "")

    if not wsurl:
        return {"href": url, "error": "missing webSocketDebuggerUrl", "label": label}

    try:
        async with websockets.connect(
            wsurl,
            max_size=10_000_000,
            open_timeout=WS_TIMEOUT,
            close_timeout=1,
        ) as ws:
            await ws.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": js,
                    "returnByValue": True,
                    "awaitPromise": False,
                    "userGesture": False,
                    "timeout": int(WS_TIMEOUT * 1000),
                },
            }))

            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)
                payload = json.loads(msg)
                if payload.get("id") != 1:
                    continue

                result = payload.get("result", {})
                if "exceptionDetails" in result:
                    return {
                        "href": url,
                        "label": label,
                        "error": "Runtime.evaluate exception",
                        "exceptionDetails": result.get("exceptionDetails"),
                    }

                return result.get("result", {}).get("value")
    except Exception as e:
        return {"href": url, "label": label, "error": str(e)}


async def run_once(refresh_sec: int):
    tabs = [t for t in get_tabs() if is_main_page_target(t)]
    results = []

    for tab in tabs:
        # Først: kort CSS/DOM hide. Dette må ikke klikke/reloade siden.
        hide_result = await evaluate_js(tab, HIDE_JS, "hide")
        results.append(hide_result)

        # Countdown/refresh evalueres også når refresh_sec=0, så en tidligere
        # countdown-bar fjernes straks, hvis intervallet slås fra fra backend.
        countdown_js = COUNTDOWN_JS.replace("__REFRESH_SEC__", str(refresh_sec)).replace("__START_DELAY_SEC__", str(START_DELAY_SEC))
        countdown_result = await evaluate_js(tab, countdown_js, "countdown")
        if isinstance(countdown_result, dict):
            hide_result = dict(hide_result or {})
            hide_result["countdown"] = countdown_result
            results[-1] = hide_result

    return results


async def _async_main():
    initial_refresh_sec = get_refresh_sec()
    log(f"Starter v{VERSION}. DevTools={DEBUG_URL}, interval={INTERVAL}s, refresh={initial_refresh_sec}s, ws_timeout={WS_TIMEOUT}s, start_delay={START_DELAY_SEC}s, cookie_mode={COOKIE_MODE}, aggressive_hide={ENABLE_AGGRESSIVE_HIDE}, native_block={ENABLE_NATIVE_BLOCK}, authority=display_desired_configuration, config={CONFIG_PATH}")

    last_summary = 0.0
    last_error = ""
    last_refresh_sec = initial_refresh_sec

    while True:
        try:
            refresh_sec = get_refresh_sec()
            if refresh_sec != last_refresh_sec:
                log(f"Browser refresh-interval ændret: {last_refresh_sec}s -> {refresh_sec}s")
                last_refresh_sec = refresh_sec
            results = await run_once(refresh_sec)

            for r in results:
                if isinstance(r, dict) and r.get("error"):
                    msg = json.dumps(r, ensure_ascii=False)[:1400]
                    if msg != last_error:
                        log(f"FEJL evaluate: {msg}")
                        last_error = msg

            now = time.monotonic()
            summary_interval = 10 if results else max(10, int(EMPTY_SUMMARY_INTERVAL_SEC or 60))
            if now - last_summary > summary_interval:
                if results:
                    for r in results:
                        if isinstance(r, dict):
                            log(
                                "status "
                                f"url={r.get('href')} "
                                f"readyState={r.get('readyState')} "
                                f"skipped={r.get('skipped')} "
                                f"cookieMode={r.get('cookieMode')} "
                                f"accepted={r.get('accepted')} "
                                f"acceptResult={r.get('acceptResult')} "
                                f"marker={r.get('marker')} "
                                f"hidden={r.get('hidden')} "
                                f"overlay={r.get('overlay')} "
                                f"css={r.get('css')} "
                                f"countdown={r.get('countdown')}"
                            )
                        else:
                            log(f"status non-dict={r!r}")
                else:
                    log("Ingen main page http(s)-tabs fundet eller Chrome ikke klar.")
                last_summary = now
        except Exception as e:
            log(f"FEJL i loop: {e}")

        await asyncio.sleep(INTERVAL)


def main() -> int:
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        log("Stopper.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
