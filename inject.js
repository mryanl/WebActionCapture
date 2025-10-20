(() => {
  if (window.__recorderAttached) return;
  window.__recorderAttached = true;

  // lightweight id
  const pid = (crypto?.randomUUID?.() || Math.random().toString(16).slice(2)).slice(0,8);
  const log = (obj) => {
    try { console.log(JSON.stringify({ __rec: 1, page_id: pid, ...obj })); }
    catch { console.log(JSON.stringify({ __rec: 1, page_id: pid, type: "log_error" })); }
  };


  const isText = (el) => {
    if (!el || !el.tagName) return false;
    const t = el.tagName.toLowerCase();
    if (t === 'textarea') return true;
    if (t !== 'input') return false;
    const typ = (el.type || 'text').toLowerCase();
    return ['text','search','email','url','tel','number'].includes(typ);
  };
  const isPassword = (el) => el?.tagName?.toLowerCase()==='input' && (el.type||'').toLowerCase()==='password';

  let lastMouse = 0;
  document.addEventListener('mousemove', (e) => {
    const now = Date.now();
    if (now - lastMouse > 100) {
      log({ type:'mouse_move', x:e.clientX, y:e.clientY, ts: now });
      lastMouse = now;
    }
  }, { capture:true, passive:true });

  document.addEventListener('click', (e) => {
    const a = e.target?.closest?.('a');
    log({
      type:'click',
      x:e.clientX, y:e.clientY,
      element: e.target?.tagName || 'UNKNOWN',
      href: a ? (a.href || null) : null,
      ts: Date.now()
    });
  }, { capture:true });

  let scrolling = false, sx=0, sy=0, st=0, tmr;
  addEventListener('scroll', () => {
    const now = Date.now();
    if (!scrolling) {
      scrolling = true; sx=scrollX; sy=scrollY; st=now;
      log({ type:'scroll_start', startX:sx, startY:sy, ts: now });
    }
    clearTimeout(tmr);
    tmr = setTimeout(() => {
      const ex = scrollX, ey = scrollY, dur = Date.now() - st;
      log({ type:'scroll_end', startX:sx, startY:sy, endX:ex, endY:ey, dx:ex-sx, dy:ey-sy, duration_ms:dur, ts: Date.now() });
      scrolling = false;
    }, 400);
  }, { capture:true, passive:true });

  document.addEventListener('input', (e) => {
    const el = e.target;
    if (!isText(el) || isPassword(el)) return;
    let val = ''; try { val = String(el.value ?? ''); } catch {}
    log({ type:'type', element: el.tagName, id: el.id || null, name: el.name || null, value: val, ts: Date.now() });
  }, { capture:true });

  document.addEventListener('keydown', (e) => {
    const el = e.target;
    if (!isText(el) || isPassword(el)) return;
    if (e.key === 'Enter') {
      let val = ''; try { val = String(el.value ?? ''); } catch {}
      log({ type:'type_commit', key:'Enter', element: el.tagName, id: el.id || null, name: el.name || null, value: val, ts: Date.now() });
    }
  }, { capture:true });

  document.addEventListener('blur', (e) => {
    const el = e.target;
    if (!isText(el) || isPassword(el)) return;
    let val = ''; try { val = String(el.value ?? ''); } catch {}
    log({ type:'type_commit', key:'blur', element: el.tagName, id: el.id || null, name: el.name || null, value: val, ts: Date.now() });
  }, true);


  window.addEventListener('focus', () => {
    log({ type: 'window_focus', ts: Date.now() });
  }, true);

  window.addEventListener('blur', () => {
    log({ type: 'window_blur', ts: Date.now() });
  }, true);

  document.addEventListener('visibilitychange', () => {
    log({
        type: document.hidden ? 'tab_hidden' : 'tab_visible',
        visibility: document.visibilityState,
        url: window.location.href,
        title: document.title,
        ts: Date.now()
    });
}, true);

    let lastUrl = window.location.href;
    const checkUrlChange = () => {
        const currentUrl = window.location.href;
        if (currentUrl !== lastUrl) {
            log({
                type: 'navigation',
                from: lastUrl,
                to: currentUrl,
                ts: Date.now()
            });
            lastUrl = currentUrl;
        }
    };

        // Override history methods to catch SPA navigation
    const originalPushState = history.pushState;
    const originalReplaceState = history.replaceState;
    
    history.pushState = function(...args) {
        originalPushState.apply(this, args);
        checkUrlChange();
    };
    
    history.replaceState = function(...args) {
        originalReplaceState.apply(this, args);
        checkUrlChange();
    };
    
    // Also listen for popstate (back/forward buttons)
    window.addEventListener('popstate', () => {
        checkUrlChange();
    });
    
    // Initial page load
  log({
    type: 'recorder_init',
    url: window.location.href,
    title: document.title,
    userAgent: navigator.userAgent,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    ts: Date.now(),
    t_since_nav_ms: tRel()
  });
})();

