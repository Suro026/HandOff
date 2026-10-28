// Light / dark switch. Follows the system until the person picks one; the pick is remembered if the browser allows it.
(function () {
  var KEY = 'handoff-theme', root = document.documentElement;
  function read() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function write(v) { try { localStorage.setItem(KEY, v); } catch (e) { /* remembering is optional */ } }
  function current() {
    return root.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  }
  var saved = read();
  if (saved === 'light' || saved === 'dark') root.dataset.theme = saved;

  document.addEventListener('DOMContentLoaded', function () {
    var host = document.getElementById('theme-slot');
    if (!host) return;
    var NS = 'http://www.w3.org/2000/svg';
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'icon-btn theme-btn';
    function paint() {
      var dark = current() === 'dark';
      b.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
      b.title = b.getAttribute('aria-label');
      b.textContent = '';
      var s = document.createElementNS(NS, 'svg');
      s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('width', '20'); s.setAttribute('height', '20');
      s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor'); s.setAttribute('stroke-width', '2');
      s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round'); s.setAttribute('aria-hidden', 'true');
      var p = document.createElementNS(NS, 'path');
      if (dark) { // sun
        p.setAttribute('d', 'M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4M12 8a4 4 0 100 8 4 4 0 000-8z');
      } else { // moon
        p.setAttribute('d', 'M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z');
      }
      s.appendChild(p); b.appendChild(s);
    }
    b.addEventListener('click', function () {
      var next = current() === 'dark' ? 'light' : 'dark';
      root.dataset.theme = next; write(next); paint();
    });
    paint(); host.appendChild(b);
  });
})();
