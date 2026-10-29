/* Owner dashboard. Plain JavaScript, no build step. All text is inserted with textContent, never innerHTML. */
(function () {
  'use strict';
  var app = document.getElementById('app');
  var csrf = null;
  var sharing = null;   // latest /api/sharing
  var diag = null;      // latest /api/diagnostics
  var pollTimer = null;
  var returnTo = null;  // where to go back to after the owner picks a sharing method
  var linkListRefresh = function () { return Promise.resolve(); };  // set by the project page: redraw its list of links

  function h(tag, attrs) {
    var el = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (k) {
      if (k === 'class') el.className = attrs[k];
      else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== false && attrs[k] != null) el.setAttribute(k, attrs[k] === true ? '' : attrs[k]);
    });
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c == null || c === false) continue;
      el.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
    }
    return el;
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
  function size(n) {
    var u = ['B', 'KB', 'MB', 'GB', 'TB'], i = 0, v = n;
    while (v >= 1000 && i < u.length - 1) { v /= 1000; i++; }
    return (i === 0 ? v : v.toFixed(1)) + ' ' + u[i];
  }
  function when(s) { return s ? new Date(s).toLocaleString() : 'never'; }

  function api(method, path, body) {
    var opts = { method: method, headers: {}, credentials: 'same-origin' };
    if (csrf) opts.headers['X-CSRF-Token'] = csrf;
    if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    return fetch(path, opts).then(function (r) {
      if (r.status === 204) return null;
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) { var e = new Error(detail(data) || r.statusText); e.status = r.status; e.data = data; throw e; }
        return data;
      });
    });
  }
  function detail(d) {
    if (!d || !d.detail) return '';
    return typeof d.detail === 'string' ? d.detail : d.detail.map(function (x) { return x.msg; }).join(' ');
  }
  function errBox(msg) { return h('p', { class: 'err', role: 'alert' }, msg); }
  // ---- small icons (inline SVG, no external files)
  var SVG_NS = 'http://www.w3.org/2000/svg';
  function icon(kind) {
    var svg = document.createElementNS(SVG_NS, 'svg');
    [['viewBox', '0 0 24 24'], ['width', '18'], ['height', '18'], ['fill', 'none'], ['stroke', 'currentColor'], ['stroke-width', '2'],
      ['stroke-linecap', 'round'], ['stroke-linejoin', 'round'], ['aria-hidden', 'true']].forEach(function (a) { svg.setAttribute(a[0], a[1]); });
    (kind === 'check' ? ['M20 6 9 17l-5-5'] : ['M9 9h11v11H9z', 'M5 15V5h10']).forEach(function (d) {
      var p = document.createElementNS(SVG_NS, 'path'); p.setAttribute('d', d); svg.appendChild(p);
    });
    return svg;
  }
  function fallbackCopy(text) {
    var ta = h('textarea', { 'aria-hidden': 'true', class: 'offscreen' }); ta.value = text; document.body.appendChild(ta);
    ta.select(); var ok = false; try { ok = document.execCommand('copy'); } catch (e) {} document.body.removeChild(ta); return ok;
  }
  /** A copy icon button. `getText` may return a string or a promise; `onError` shows a problem to the owner. */
  function copyButton(getText, label, onError) {
    var b = h('button', { class: 'icon-btn', type: 'button', title: 'Copy link', 'aria-label': label || 'Copy link' }, icon('copy'));
    b.addEventListener('click', function () {
      Promise.resolve().then(getText).then(function (text) {
        var done = function () { flash(b, true); };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          return navigator.clipboard.writeText(text).then(done, function () { flash(b, fallbackCopy(text)); });
        }
        flash(b, fallbackCopy(text));
      }).catch(function (e) { if (onError) onError(e); });
    });
    return b;
  }
  function flash(b, ok) {
    clear(b); b.appendChild(icon(ok ? 'check' : 'copy')); b.classList.toggle('done', ok);
    b.title = ok ? 'Copied' : 'Could not copy. Select the link and copy it by hand.';
    if (!ok) {  // leave the link selected so Ctrl+C works
      var code = b.parentNode && b.parentNode.querySelector('code');
      if (code && window.getSelection) { var rng = document.createRange(); rng.selectNodeContents(code); var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(rng); }
    }
    var live = b.parentNode && b.parentNode.querySelector('.copied-note'); if (live) live.textContent = ok ? 'Copied' : 'Could not copy';
    setTimeout(function () { clear(b); b.appendChild(icon('copy')); b.classList.remove('done'); b.title = 'Copy link'; if (live) live.textContent = ''; }, 1800);
  }
  /** The link in a box, with a copy icon next to it. */
  function linkBox(url, label) {
    return h('div', { class: 'linkbox' }, h('code', null, url), copyButton(function () { return url; }, label), h('span', { class: 'copied-note small', role: 'status' }));
  }

  // ---------------------------------------------------------------- session
  function boot() {
    api('GET', '/api/auth/session').then(function (s) {
      csrf = s.csrf;
      stopPolling();
      document.getElementById('who').textContent = '';
      clear(document.getElementById('banner'));
      if (s.setup_needed) return viewSetup();
      if (!s.authenticated) return viewLogin();
      var who = document.getElementById('who');
      who.appendChild(h('span', { class: 'muted small' }, s.username + ' '));
      who.appendChild(h('button', { class: 'btn', onclick: function () { api('POST', '/api/auth/logout').then(boot); } }, 'Sign out'));
      startPolling();
      route();
    }).catch(function (e) { clear(app); app.appendChild(errBox(e.message)); });
  }

  function authForm(title, intro, submitLabel, onSubmit, withHint) {
    clear(app);
    var err = h('div');
    var u = h('input', { id: 'u', name: 'username', autocomplete: 'username', required: true });
    var p = h('input', { id: 'p', name: 'password', type: 'password', autocomplete: withHint ? 'new-password' : 'current-password', required: true, minlength: withHint ? 10 : 1 });
    var form = h('form', { class: 'form', onsubmit: function (ev) {
      ev.preventDefault(); clear(err);
      onSubmit(u.value, p.value).catch(function (e) { err.appendChild(errBox(e.message)); });
    } },
      h('label', { for: 'u' }, 'Username', u),
      h('label', { for: 'p' }, withHint ? 'Password (at least 10 characters)' : 'Password', p),
      err,
      h('button', { class: 'btn primary', type: 'submit' }, submitLabel));
    app.appendChild(h('h1', null, title));
    app.appendChild(h('p', { class: 'muted' }, intro));
    app.appendChild(form);
  }
  function viewSetup() {
    authForm('Welcome to Handoff', 'Create the account for this computer. It stays on your computer; nothing is sent anywhere.', 'Create account',
      function (u, p) { return api('POST', '/api/setup', { username: u, password: p }).then(boot); }, true);
  }
  function viewLogin() {
    authForm('Sign in', 'Handoff dashboard.', 'Sign in',
      function (u, p) { return api('POST', '/api/auth/login', { username: u, password: p }).then(boot); }, false);
  }

  // ------------------------------------------------- connection status bar
  var STATE_TEXT = { online: 'Sharing online', connecting: 'Connecting…', reconnecting: 'Reconnecting…', offline: 'Sharing offline', failed: 'Sharing problem' };

  function startPolling() { refreshStatus(); pollTimer = setInterval(refreshStatus, 2500); }
  function stopPolling() { if (pollTimer) clearInterval(pollTimer); pollTimer = null; }

  function refreshStatus() {
    return Promise.all([api('GET', '/api/sharing'), api('GET', '/api/diagnostics')]).then(function (r) {
      sharing = r[0]; diag = r[1];
      renderBanner();
      if (location.hash === '#/sharing') updateSharingPanel();
    }).catch(function () {});
  }

  function renderBanner() {
    var b = document.getElementById('banner');
    var openBefore = b.querySelector('details.bar-details');
    var wasOpen = !!(openBefore && openBefore.open);  // the bar redraws every few seconds; keep "Details" open if it was
    clear(b);
    if (!sharing) return;
    if (!sharing.managed) {
      b.appendChild(h('span', null, 'Free disk space: ' + size(diag.free_bytes) + ' · Share links use ' + diag.share_base + ' '));
      diag.warnings.forEach(function (w) { b.appendChild(h('div', { class: 'warn' }, w)); });
      return;
    }
    var st = sharing.state;
    var row = h('div', { class: 'row' });
    var elapsed = (st === 'connecting' || st === 'reconnecting') ? ' (' + Math.max(0, Math.round(Date.now() / 1000 - sharing.since)) + ' s)' : '';
    var pillText = (STATE_TEXT[st] || st) + (st === 'online' && sharing.verified === false ? ' · not confirmed' : '');
    // One short line in the bar. The full explanation and the address are under "Details".
    var hint = st === 'online' ? (sharing.temporary ? 'Temporary link' : (sharing.provider_label || '')) : sharing.message + elapsed;
    var left = h('div', { class: 'bar-left' },
      h('span', { class: 'pill ' + st }, pillText),
      h('span', { class: 'small bar-hint' }, hint));
    if (st !== 'offline') {
      var det = h('details', { class: 'bar-details' }, h('summary', null, 'Details'),
        h('p', { class: 'small' }, sharing.message),
        sharing.base_url ? linkBox(sharing.base_url, 'Copy address') : null);
      det.open = wasOpen;
      left.appendChild(det);
    }
    var right = h('div', { class: 'row tight' });
    right.appendChild(h('a', { class: 'small', href: '#/sharing' }, 'Change how clients connect'));
    if (st !== 'offline') right.appendChild(h('button', { class: 'btn', type: 'button', onclick: function () { api('POST', '/api/sharing/stop').then(refreshStatus); } }, 'Stop sharing'));
    else if (sharing.provider && (sharing.provider !== 'quick' || sharing.quick_consented) && sharing.provider !== 'tailscale') {
      right.appendChild(h('button', { class: 'btn primary', type: 'button', onclick: function () { startProvider(sharing.provider).catch(function () {}); } }, 'Start sharing'));
    }
    right.appendChild(h('button', { class: 'btn danger', type: 'button', onclick: function () {
      if (confirm('Quit Handoff? Your links will stop working until you open it again.')) api('POST', '/api/app/quit', {}).then(function () {
        clear(document.getElementById('who')); stopPolling(); clear(b);
        clear(app); app.appendChild(h('h1', null, 'Handoff has quit')); app.appendChild(h('p', { class: 'muted' }, 'Sharing is off. Open Handoff again to continue. You can close this tab.'));
      });
    } }, 'Quit Handoff'));
    row.appendChild(left); row.appendChild(right);
    b.appendChild(row);
    if (sharing.address_changed) {
      b.appendChild(h('div', { class: 'warn' },
        'Your sharing address changed, so links you sent earlier no longer work. Open a project and use the copy icon to get the new links to send. ',
        h('button', { class: 'linkbtn', type: 'button', onclick: function () { api('POST', '/api/sharing/dismiss-address-change').then(refreshStatus); } }, 'Dismiss')));
    }
  }

  // ----------------------------------------------------------------- routing
  window.addEventListener('hashchange', function () { if (csrf) route(); });
  function route() {
    var m = location.hash.match(/^#\/project\/([a-f0-9]+)/);
    if (m) return viewProject(m[1]);
    if (location.hash === '#/sharing') return viewSharing();
    viewProjects();
  }

  // ---------------------------------------------------------------- sharing
  function startProvider(provider, extra) {
    var body = Object.assign({ provider: provider }, extra || {});
    return api('POST', '/api/sharing/start', body).then(function (s) { sharing = s; renderBanner(); return s; });
  }
  function waitOnline(timeoutMs, onTick) {
    var end = Date.now() + timeoutMs;
    return new Promise(function (resolve, reject) {
      (function tick() {
        api('GET', '/api/sharing').then(function (s) {
          sharing = s; renderBanner(); if (onTick) onTick(s);
          if (s.state === 'online') return resolve(s);
          if (s.state === 'failed' || s.state === 'offline') return reject(new Error(s.message));
          if (Date.now() > end) return reject(new Error('Sharing is taking longer than expected. ' + s.message));
          setTimeout(tick, 1000);
        }).catch(reject);
      })();
    });
  }
  /** Desktop only: make sure sharing is online, starting the last-used method if needed. */
  function ensureOnline(onTick) {
    if (!sharing || !sharing.managed || sharing.state === 'online') return Promise.resolve();
    var needsChoice = !sharing.provider || (sharing.provider === 'quick' && !sharing.quick_consented) || sharing.provider === 'tailscale';
    if (needsChoice) {
      returnTo = location.hash;  // come straight back here after choosing
      location.hash = '#/sharing';
      return Promise.reject(new Error('First choose who will open your link.'));
    }
    var start = (sharing.state === 'offline' || sharing.state === 'failed') ? startProvider(sharing.provider) : Promise.resolve();
    return start.then(function () { return waitOnline(150000, onTick); });
  }

  function viewSharing() {
    clear(app);
    app.appendChild(h('p', null, h('a', { href: returnTo || '#/' }, '← Back')));
    app.appendChild(h('h1', null, 'Who will open your link?'));
    app.appendChild(h('p', { class: 'muted' }, 'Pick one. You can change it any time.'));
    app.appendChild(h('div', { id: 'sharing-panel', class: 'grid' }));
    updateSharingPanel();
  }

  /** After choosing a method, go straight back to what the owner was doing. */
  function chosen() {
    if (returnTo) { var t = returnTo; returnTo = null; location.hash = t; } else { updateSharingPanel(); }
  }

  function option(key, title, badge, line, controls) {
    var active = sharing && sharing.provider === key && sharing.state !== 'offline';
    return h('div', { class: 'card' + (active ? ' shown' : '') },
      h('div', { class: 'row' }, h('h3', null, title), badge ? h('span', { class: 'chip' }, badge) : null, active ? h('span', { class: 'pill ' + sharing.state }, STATE_TEXT[sharing.state]) : null),
      h('p', { class: 'muted' }, line), controls);
  }

  function updateSharingPanel() {
    var panel = document.getElementById('sharing-panel');
    if (!panel || !sharing) return;
    if (panel.contains(document.activeElement) && document.activeElement.tagName === 'INPUT') return; // don't disturb typing
    var openMore = panel.querySelector('details.more') && panel.querySelector('details.more').open;
    clear(panel);
    var err = h('div');
    if (!sharing.managed) {
      panel.appendChild(h('div', { class: 'card' }, h('p', null, 'This copy of Handoff is running in server mode. Set PUBLIC_BASE_URL to the address clients should use. See the README.')));
      return;
    }
    panel.appendChild(err);
    var busy = sharing.state === 'connecting';
    function go(provider, extra) {
      clear(err);
      return startProvider(provider, extra).then(chosen).catch(function (e) { err.appendChild(errBox(e.message)); });
    }

    // 1. Anyone, over the internet (Quick Share)
    var agree = h('input', { type: 'checkbox', id: 'qs-agree' });
    var terms = h('div', { hidden: true, class: 'grid' },
      h('ul', { class: 'plain-list' },
        h('li', null, 'The link is temporary. It changes if Handoff restarts or reconnects.'),
        h('li', null, 'It uses a free service meant for testing. It may be slow or stop working.'),
        h('li', null, 'Your computer must stay on and online.')),
      h('details', null, h('summary', null, 'Full details'), h('p', { class: 'small muted' }, sharing.quick_terms)),
      h('label', { class: 'check', for: 'qs-agree' }, agree, 'OK, I understand'));
    var internetBtn = h('button', { class: 'btn primary', type: 'button', disabled: busy, onclick: function () {
      clear(err);
      if (!sharing.quick_consented && terms.hidden) { terms.hidden = false; internetBtn.textContent = 'Continue'; return; }
      if (!sharing.quick_consented && !agree.checked) { err.appendChild(errBox('Tick “OK, I understand” to continue.')); return; }
      go('quick', { accept_quick_terms: true });
    } }, 'Use this');
    panel.appendChild(option('quick', 'Anyone, over the internet', 'Easiest',
      'Works from anywhere. Nothing to set up.',
      h('div', { class: 'grid' }, terms, internetBtn,
        sharing.helper && sharing.helper.phase === 'downloading' ? h('p', { class: 'small muted' }, 'Getting ready… ' + sharing.helper.percent + '%') : null)));

    // 2. Same Wi-Fi
    panel.appendChild(option('lan', 'Someone on my Wi-Fi', null,
      'For the same office or home network only.',
      h('button', { class: 'btn', type: 'button', disabled: busy, onclick: function () { go('lan'); } }, 'Use this')));

    // More options
    var url = h('input', { id: 'cu', placeholder: 'https://files.example.com', value: sharing.custom_url || '' });
    var tsNote = sharing.tailscale_command ? h('p', { class: 'small' }, 'Run this once in a terminal: ', h('code', null, sharing.tailscale_command)) : null;
    var more = h('details', { class: 'more' },
      h('summary', null, 'More options'),
      h('div', { class: 'grid more-body' },
        h('form', { class: 'form', onsubmit: function (ev) { ev.preventDefault(); go('custom', { custom_url: url.value }); } },
          h('label', { for: 'cu' }, 'My own web address', url),
          h('p', { class: 'muted small' }, 'For a stable link, if you already have an address that points to this computer’s sharing port (' + sharing.share_port + ').'),
          h('button', { class: 'btn', type: 'submit', disabled: busy }, 'Use this address')),
        h('div', { class: 'grid' },
          h('strong', null, 'Tailscale Funnel (advanced)'),
          h('p', { class: 'muted small' }, 'Only if you already use Tailscale. Handoff only reads its status, and never changes your Tailscale settings.'),
          tsNote, h('button', { class: 'btn', type: 'button', onclick: function () { go('tailscale'); } }, 'Check Tailscale'))));
    if (openMore) more.open = true;
    panel.appendChild(more);
  }

  // ---------------------------------------------------------------- projects
  function viewProjects() {
    clear(app);
    app.appendChild(h('h1', null, 'Projects'));
    var title = h('input', { id: 'pt', required: true, maxlength: 200, placeholder: 'Brand film for Acme' });
    var err = h('div');
    app.appendChild(h('form', { class: 'form', onsubmit: function (ev) {
      ev.preventDefault(); clear(err);
      api('POST', '/api/projects', { title: title.value }).then(function (p) { location.hash = '#/project/' + p.id; })
        .catch(function (e) { err.appendChild(errBox(e.message)); });
    } }, h('label', { for: 'pt' }, 'New project', title), err, h('button', { class: 'btn primary', type: 'submit' }, 'Create project')));
    var list = h('div', { class: 'grid' });
    app.appendChild(h('h2', null, 'Your projects'));
    app.appendChild(list);
    api('GET', '/api/projects').then(function (rows) {
      if (!rows.length) list.appendChild(h('p', { class: 'muted' }, 'No projects yet. Create one above, then add the finished files.'));
      rows.forEach(function (p) {
        list.appendChild(h('a', { class: 'card plain', href: '#/project/' + p.id },
          h('div', { class: 'row' }, h('h3', null, p.title), h('span', { class: 'muted small' }, p.file_count + ' file(s) · ' + size(p.total_bytes) + ' · ' + p.open_links + ' open link(s)'))));
      });
    });
  }

  function viewProject(pid) {
    clear(app);
    api('GET', '/api/projects/' + pid).then(function (p) { renderProject(p); })
      .catch(function (e) { app.appendChild(errBox(e.message)); app.appendChild(h('a', { href: '#/' }, 'Back to projects')); });
  }

  function renderProject(p) {
    clear(app);
    app.appendChild(h('p', null, h('a', { href: '#/' }, '← All projects')));
    app.appendChild(h('div', { class: 'row' }, h('h1', null, p.title),
      h('button', { class: 'btn danger', onclick: function () {
        if (confirm('Delete this project and all of its files from disk? This cannot be undone.'))
          api('DELETE', '/api/projects/' + p.id).then(function () { location.hash = '#/'; });
      } }, 'Delete project')));

    // --- files
    app.appendChild(h('h2', null, 'Files'));
    var uploads = h('div', { class: 'grid' });
    var input = h('input', { type: 'file', multiple: true, id: 'fi', 'aria-label': 'Choose files to add' });
    var drop = h('div', { class: 'drop' }, h('p', null, 'Drop finished files here, or choose them.'), input,
      h('p', { class: 'muted small' }, 'Handoff copies files into its own storage folder, so your originals stay where they are and the copy uses extra disk space. Files are stored exactly as they are: nothing is compressed, resized or watermarked.'));
    ['dragenter', 'dragover'].forEach(function (n) { drop.addEventListener(n, function (e) { e.preventDefault(); drop.classList.add('over'); }); });
    ['dragleave', 'drop'].forEach(function (n) { drop.addEventListener(n, function (e) { e.preventDefault(); drop.classList.remove('over'); }); });
    drop.addEventListener('drop', function (e) { queue(e.dataTransfer.files); });
    input.addEventListener('change', function () { queue(input.files); input.value = ''; });
    app.appendChild(drop);
    app.appendChild(uploads);

    var pending = 0;
    var chain = Promise.resolve();
    function queue(files) {
      var list = Array.prototype.slice.call(files);
      if (!list.length) return;
      var total = list.reduce(function (a, f) { return a + f.size; }, 0);
      var free = diag ? diag.free_bytes : null, reserve = diag ? diag.reserve_bytes : 0;
      if (free !== null && total + reserve > free) {
        uploads.appendChild(errBox('Not enough free disk space. These ' + list.length + ' file(s) are ' + size(total) + ', and Handoff keeps ' + size(reserve) + ' free; only ' + size(free) + ' is free now. Free up space or choose fewer files.'));
        return;
      }
      if (total >= 1e9 || (free !== null && total > free * 0.1)) {
        var msg = 'Handoff will copy ' + size(total) + ' into its storage folder. Your original files stay where they are, so this uses ' + size(total) + ' of extra disk space' +
          (free !== null ? ' (you have ' + size(free) + ' free)' : '') + '. Large files can take a while to copy. Continue?';
        if (!confirm(msg)) return;
      }
      list.forEach(function (f) {
        pending++;
        var bar = h('i'), status = h('span', { class: 'muted small' }, 'Waiting…');
        uploads.appendChild(h('div', { class: 'card' }, h('div', { class: 'row' }, h('strong', null, f.name), status), h('div', { class: 'progress' }, bar)));
        chain = chain.then(function () { return send(f, bar, status); }).then(function () {
          pending--; if (!pending) { refreshStatus(); viewProject(p.id); }
        });
      });
    }
    function send(file, bar, status) {
      return new Promise(function (resolve) {
        var x = new XMLHttpRequest();
        x.open('PUT', '/api/projects/' + p.id + '/files?name=' + encodeURIComponent(file.name));
        x.setRequestHeader('X-CSRF-Token', csrf);
        x.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
        x.upload.onprogress = function (e) {
          if (e.lengthComputable) { bar.style.width = (100 * e.loaded / e.total).toFixed(1) + '%'; status.textContent = size(e.loaded) + ' of ' + size(e.total); }
        };
        x.onload = function () {
          var d = {}; try { d = JSON.parse(x.responseText); } catch (e) {}
          if (x.status === 201) { bar.style.width = '100%'; status.textContent = 'Stored. SHA-256 ' + d.sha256.slice(0, 12) + '…'; }
          else { status.textContent = 'Failed: ' + (detail(d) || x.statusText); status.className = 'err small'; }
          resolve();
        };
        x.onerror = function () { status.textContent = 'Failed: connection lost.'; status.className = 'err small'; resolve(); };
        x.send(file); // the browser streams the File from disk; it is not read into memory here
      });
    }

    var ftable = h('table', null, h('thead', null, h('tr', null, h('th', null, 'Name'), h('th', null, 'Size'), h('th', null, 'Type'), h('th', null, 'SHA-256'), h('th', null, ''))));
    var tb = h('tbody');
    p.files.forEach(function (f) {
      tb.appendChild(h('tr', null,
        h('td', { class: 'break' }, f.name, f.status === 'missing' ? h('span', { class: 'err small' }, ' (missing on disk)') : null),
        h('td', null, size(f.size)), h('td', null, f.mime + (f.previewable ? ' · previewable' : '')),
        h('td', null, h('code', null, f.sha256.slice(0, 16) + '…')),
        h('td', null, h('button', { class: 'btn danger', 'aria-label': 'Delete ' + f.name, onclick: function () {
          if (confirm('Delete ' + f.name + '?')) api('DELETE', '/api/files/' + f.id).then(function () { viewProject(p.id); });
        } }, 'Delete'))));
    });
    ftable.appendChild(tb);
    app.appendChild(p.files.length ? ftable : h('p', { class: 'muted' }, 'No files yet.'));

    // --- links
    app.appendChild(h('h2', null, 'Share with your client'));
    app.appendChild(linkForm(p));
    var copyMsg = h('div', { role: 'status' });
    var linkHost = h('div');
    /** Draws the list of links. Called at first, and again after a new link is created. */
    function drawLinks(links) {
    clear(linkHost);
    var linkList = h('div', { class: 'grid' });
    links.forEach(function (l) {
      var meta = [l.access === 'view_only' ? 'View only' : 'View and download', l.scope === 'files' ? 'chosen files' : 'whole project'];
      if (l.has_password) meta.push('password');
      if (l.expires_at) meta.push('expires ' + when(l.expires_at));
      meta.push(l.download_count + (l.max_downloads ? ' of ' + l.max_downloads : '') + ' download(s)');
      meta.push('last opened ' + when(l.last_accessed_at));
      var actions = h('div', { class: 'row tight' });
      if (l.status !== 'revoked') {
        if (l.recoverable) {
          actions.appendChild(copyButton(function () {
            clear(copyMsg);
            return ensureOnline(function (s) { copyMsg.textContent = s.message; })
              .then(function () { return api('GET', '/api/links/' + l.id + '/url'); })
              .then(function (r) { clear(copyMsg); return r.url; });
          }, 'Copy link ' + (l.label || ''), function (er) { clear(copyMsg); copyMsg.appendChild(errBox(er.message)); }));
        }
        actions.appendChild(h('button', { class: 'btn danger', type: 'button', onclick: function () {
          if (confirm('Revoke this link? It stops working immediately.')) api('DELETE', '/api/links/' + l.id).then(function () { viewProject(p.id); });
        } }, 'Revoke'));
      }
      linkList.appendChild(h('div', { class: 'card linkrow' },
        h('div', { class: 'row' }, h('strong', null, l.label || 'Untitled link'), h('span', { class: 'chip ' + l.status }, l.status)),
        h('p', { class: 'muted small' }, meta.join(' · ') + (!l.recoverable && l.status !== 'revoked' ? ' · can’t be shown again' : '')),
        actions));
    });
    linkHost.appendChild(links.length ? linkList : h('p', { class: 'muted' }, 'No links yet.'));
    }
    drawLinks(p.links);
    app.appendChild(linkHost);
    app.appendChild(copyMsg);
    linkListRefresh = function () { return api('GET', '/api/projects/' + p.id).then(function (np) { drawLinks(np.links); }); };

    // --- activity
    app.appendChild(h('h2', null, 'Activity'));
    var act = h('div');
    app.appendChild(act);
    api('GET', '/api/access-log?project_id=' + p.id + '&limit=50').then(function (rows) {
      if (!rows.length) return act.appendChild(h('p', { class: 'muted' }, 'Nothing yet. Views, previews and downloads on your links appear here.'));
      var t = h('table', null, h('thead', null, h('tr', null, h('th', null, 'When'), h('th', null, 'Link'), h('th', null, 'Event'), h('th', null, 'File'))));
      var b = h('tbody');
      rows.forEach(function (r) { b.appendChild(h('tr', null, h('td', null, when(r.at)), h('td', null, r.link), h('td', null, r.event), h('td', { class: 'break' }, r.file || ''))); });
      t.appendChild(b); act.appendChild(t);
    });
  }

  function linkForm(p) {
    var result = h('div'), err = h('div'), progress = h('p', { class: 'muted small', role: 'status' });
    var label = h('input', { id: 'll', maxlength: 200, placeholder: 'Final delivery for Riya' });
    var access = h('select', { id: 'la' }, h('option', { value: 'download' }, 'View and download originals'), h('option', { value: 'view_only' }, 'View only'));
    var accessNote = h('p', { class: 'muted small' });
    var scope = h('select', { id: 'ls' }, h('option', { value: 'project' }, 'Everything in this project'), h('option', { value: 'files' }, 'Only the files I choose'));
    var picks = h('div', { hidden: true });
    p.files.filter(function (f) { return f.status === 'ready'; }).forEach(function (f) {
      var cb = h('input', { type: 'checkbox', value: f.id, id: 'pf' + f.id });
      picks.appendChild(h('label', { class: 'check', for: 'pf' + f.id }, cb, f.name));
    });
    var pw = h('input', { id: 'lp', type: 'password', autocomplete: 'new-password', minlength: 6, placeholder: 'Optional' });
    var exp = h('select', { id: 'le' }, h('option', { value: '' }, 'Never'), h('option', { value: '24' }, '1 day'), h('option', { value: '168' }, '7 days'), h('option', { value: '720' }, '30 days'));
    var maxd = h('input', { id: 'lm', type: 'number', min: 1, placeholder: 'No limit' });
    var maxWrap = h('label', { for: 'lm' }, 'Download limit', maxd);
    var submit = h('button', { class: 'btn primary', type: 'submit' }, 'Create share link');

    function sync() {
      picks.hidden = scope.value !== 'files';
      maxWrap.hidden = access.value === 'view_only';
      accessNote.textContent = access.value === 'view_only'
        ? 'View-only discourages casual saving. It can\'t stop someone who wants a copy: the browser still receives the file, and screens can be recorded.'
        : 'The client can preview supported files and download every file exactly as uploaded.';
    }
    access.addEventListener('change', sync); scope.addEventListener('change', sync); sync();

    var form = h('form', { class: 'card form', onsubmit: function (ev) {
      ev.preventDefault(); clear(err); clear(result); progress.textContent = '';
      var body = { label: label.value, access: access.value, scope: scope.value, file_ids: [] };
      if (scope.value === 'files') picks.querySelectorAll('input:checked').forEach(function (c) { body.file_ids.push(c.value); });
      if (pw.value) body.password = pw.value;
      if (exp.value) body.expires_in_hours = Number(exp.value);
      if (access.value === 'download' && maxd.value) body.max_downloads = Number(maxd.value);
      submit.disabled = true;
      ensureOnline(function (s) { progress.textContent = s.message; })
        .then(function () { progress.textContent = ''; return api('POST', '/api/projects/' + p.id + '/links', body); })
        .then(function (r) {
          result.appendChild(h('div', { class: 'card shown' },
            h('p', null, h('strong', null, 'Your link is ready'), ' · tap the icon to copy it'),
            linkBox(r.url, 'Copy link'),
            r.temporary ? h('p', { class: 'small warn' }, 'Temporary: it changes if Handoff restarts or reconnects. The copy icon in the list below always gives the current link.') : null,
            r.provider === 'lan' ? h('p', { class: 'small warn' }, 'Works only for people on the same Wi-Fi or network.') : null,
            !sharing || !sharing.managed ? (r.local_only ? h('p', { class: 'small err' }, 'This link only works on this computer. Set PUBLIC_BASE_URL so clients can open it.') : null) : null));
          refreshStatus();
          linkListRefresh();
        })
        .catch(function (e) { progress.textContent = ''; err.appendChild(errBox(e.message)); })
        .then(function () { submit.disabled = false; });
    } },
      h('div', { class: 'two' },
        h('label', { for: 'll' }, 'Name (for you)', label),
        h('label', { for: 'la' }, 'Access', access)),
      accessNote,
      h('details', { class: 'more' }, h('summary', null, 'More options (files, expiry, password, limit)'),
        h('div', { class: 'grid more-body' },
          h('div', { class: 'two' }, h('label', { for: 'ls' }, 'Files', scope), h('label', { for: 'le' }, 'Expires', exp)),
          picks,
          h('div', { class: 'two' }, h('label', { for: 'lp' }, 'Password', pw), maxWrap))),
      err, progress, submit);
    return h('div', null, form, result,
      h('p', { class: 'muted small' }, 'Send the link only to your client. Revoke it any time. It works only while this computer is on and sharing.'));
  }

  boot();
})();
