// Draws PDFs on view-only links with PDF.js, so the browser's own PDF viewer (with its download and print buttons)
// is not used. This is a courtesy, not protection: the browser still receives the file to show it.
import * as pdfjsLib from '/static/pdfjs/pdf.min.mjs';

pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/pdfjs/pdf.worker.min.mjs';

function fail(host, message) {
  host.textContent = '';
  const p = document.createElement('p');
  p.className = 'muted';
  p.textContent = message;
  host.appendChild(p);
}

async function show(host) {
  try {
    // url mode lets PDF.js read the file in pieces (the server supports byte ranges), which suits large documents.
    const pdf = await pdfjsLib.getDocument({ url: host.dataset.src, withCredentials: true, isEvalSupported: false }).promise;
    host.textContent = '';
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const first = await pdf.getPage(1);
    const base = first.getViewport({ scale: 1 });
    const draw = async (holder, num) => {
      const page = await pdf.getPage(num);
      const width = holder.clientWidth || host.clientWidth || 320;
      const cssScale = width / page.getViewport({ scale: 1 }).width;
      const vp = page.getViewport({ scale: cssScale * dpr });
      const canvas = document.createElement('canvas');
      canvas.width = Math.floor(vp.width);
      canvas.height = Math.floor(vp.height);
      canvas.setAttribute('role', 'img');
      canvas.setAttribute('aria-label', 'Page ' + num + ' of ' + pdf.numPages);
      holder.style.aspectRatio = '';
      holder.appendChild(canvas);
      await page.render({ canvasContext: canvas.getContext('2d'), viewport: vp }).promise;
    };
    // Pages are drawn as they come near the screen, so a long document doesn't load all at once.
    const seen = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) {
          seen.unobserve(e.target);
          draw(e.target, Number(e.target.dataset.page)).catch(() => fail(e.target, 'This page could not be shown.'));
        }
      });
    }, { rootMargin: '600px 0px' });
    for (let n = 1; n <= pdf.numPages; n++) {
      const holder = document.createElement('div');
      holder.className = 'pdf-page';
      holder.dataset.page = String(n);
      holder.style.aspectRatio = base.width + ' / ' + base.height;
      host.appendChild(holder);
      seen.observe(holder);
    }
  } catch (e) {
    fail(host, "This document couldn't be shown.");
  }
}

document.querySelectorAll('.pdf[data-src]').forEach(show);
