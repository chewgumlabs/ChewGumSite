// Dynamic ANSI window frames.
//
// Source markup per window:
//   <section class="window"
//            data-title="Profile"
//            [data-window-mode="text" | "rich"]
//            [data-experiment]>
//     <div class="window-content">
//       ... arbitrary HTML ...
//     </div>
//   </section>
//
// TWO RENDERING MODES:
//
//   "text" (default for prose):
//     Every paragraph is word-wrapped and emitted as <pre class="ansi-window">
//     with real ╔══[ Title ]══╗ top, ║ … ║ on every body row, and
//     ╚══════════╝ bottom. Full ANSI authenticity. Use for posts that are
//     just text + links.
//
//   "rich" (for interactive content):
//     Only the top and bottom frames are <pre> chars (╔══╗ / ╚══╝). The
//     body sits between them as a normal-flow div, with 1px CSS borders
//     in panel-border color simulating the ║ sides. Use whenever the
//     content includes <canvas>, <button>, <form>, complex layout, or
//     anything that can't be flattened into wrapped text.
//
// Mode is auto-detected if the source omits data-window-mode: any
// non-text element inside .window-content forces rich mode. Authors can
// override explicitly.
//
// Re-runs on resize. Author edits plain HTML — never counts columns.

(() => {
  const FRAME_TITLE_OVERHEAD = 9; // ╔═■══[ T ]╗ — 9 chars of frame around title
  const SIDE_OVERHEAD = 6;        // ║ + 2 space + 2 space + ║ (visual parity w/ 16px row height)

  /** Measure one VGA-cell width in pixels by probing 80 chars. */
  function measureCharWidth(scope) {
    const probe = document.createElement('span');
    probe.style.cssText =
      'position:absolute;visibility:hidden;white-space:pre;font:inherit;';
    probe.textContent = '─'.repeat(80);
    scope.appendChild(probe);
    const w = probe.getBoundingClientRect().width / 80;
    probe.remove();
    return w;
  }

  // Inline elements that are ATOMIC (cannot be broken across lines).
  // Currently just <a>: a link's text should stay together so a break
  // in the middle doesn't create two adjacent links to the same href.
  // Every other inline element (<em>, <strong>, <span>, <code>, etc.)
  // recurses — its tags get wrapped around each child word so wrapping
  // works normally inside.
  const ATOMIC_TAGS = new Set(['A']);

  function collapseWhitespace(text) {
    return text.replace(/\s+/g, ' ').trim();
  }

  function normalizedAtomicMarkup(node) {
    const clone = node.cloneNode(true);
    const walker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      walker.currentNode.nodeValue = collapseWhitespace(walker.currentNode.nodeValue);
    }
    return {
      visible: collapseWhitespace(clone.textContent),
      markup: clone.outerHTML,
    };
  }

  /** Word-wrap a single line of HTML to `cols` visible chars per row. */
  function wrapHtmlLine(html, cols) {
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    const words = [];
    function walk(node, openTags, closeTags) {
      if (node.nodeType === Node.TEXT_NODE) {
        const parts = node.nodeValue.split(/(\s+)/);
        for (const p of parts) {
          if (p === '') continue;
          if (/^\s+$/.test(p)) {
            words.push({ visible: ' ', markup: ' ', isSpace: true });
          } else {
            words.push({
              visible: p,
              markup: openTags + escapeHtml(p) + closeTags,
            });
          }
        }
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        if (ATOMIC_TAGS.has(node.tagName)) {
          // Whole element stays together as one wrap unit.
          const atomic = normalizedAtomicMarkup(node);
          words.push({
            visible: atomic.visible,
            markup: openTags + atomic.markup + closeTags,
          });
          return;
        }
        // Inline element — recurse, wrapping each emitted word in this
        // element's open/close tags. The output has many small <em>word</em>
        // pairs rather than one big <em>...</em>, but renders identically.
        const tag = node.tagName.toLowerCase();
        const attrs = Array.from(node.attributes)
          .map(a => ` ${a.name}="${escapeAttr(a.value)}"`).join('');
        const open = `<${tag}${attrs}>`;
        const close = `</${tag}>`;
        for (const child of node.childNodes) {
          walk(child, openTags + open, close + closeTags);
        }
      }
    }
    for (const child of tmp.childNodes) walk(child, '', '');

    // Greedy wrap: accumulate words into lines of ≤ cols visible chars.
    const lines = [];
    let lineMarkup = '';
    let lineVisible = 0;
    for (const w of words) {
      if (w.isSpace) {
        if (lineVisible === 0) continue;        // skip leading space
        if (lineVisible + 1 > cols) {
          lines.push({ markup: lineMarkup, visible: lineVisible });
          lineMarkup = ''; lineVisible = 0;
          continue;
        }
        lineMarkup += w.markup;
        lineVisible += 1;
      } else {
        if (lineVisible + w.visible.length > cols && lineVisible > 0) {
          // strip trailing space if any
          const trimmedMarkup = lineMarkup.replace(/( |&nbsp;)+$/,'');
          const trimmedVisible = trimmedMarkup === lineMarkup
            ? lineVisible : lineVisible - (lineMarkup.length - trimmedMarkup.length);
          lines.push({ markup: trimmedMarkup, visible: trimmedVisible });
          lineMarkup = ''; lineVisible = 0;
        }
        lineMarkup += w.markup;
        lineVisible += w.visible.length;
      }
    }
    if (lineMarkup) {
      const trimmedMarkup = lineMarkup.replace(/( |&nbsp;)+$/,'');
      const trimmedVisible = trimmedMarkup === lineMarkup
        ? lineVisible : lineVisible - (lineMarkup.length - trimmedMarkup.length);
      lines.push({ markup: trimmedMarkup, visible: trimmedVisible });
    }
    return lines;
  }

  function escapeHtml(s) {
    return s.replace(/[&<>]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;' }[c]));
  }
  function escapeAttr(s) {
    return s.replace(/[&"]/g, c => ({ '&':'&amp;','"':'&quot;' }[c]));
  }

  // Tags that force rich mode when present in the body.
  const RICH_TAGS = new Set([
    'CANVAS', 'BUTTON', 'FORM', 'INPUT', 'SELECT', 'TEXTAREA',
    'TABLE', 'IMG', 'SVG', 'VIDEO', 'AUDIO', 'IFRAME',
    'DL', 'DT', 'DD',
    'STYLE', 'SCRIPT',
  ]);

  function autoDetectMode(content) {
    // text mode if every descendant is a known prose element.
    const PROSE_OK = new Set(['P', 'A', 'EM', 'STRONG', 'SPAN', 'BR',
                              'CODE', 'KBD', 'SMALL', 'I', 'B']);
    const walker = document.createTreeWalker(content, NodeFilter.SHOW_ELEMENT);
    while (walker.nextNode()) {
      const n = walker.currentNode;
      if (RICH_TAGS.has(n.tagName)) return 'rich';
      if (!PROSE_OK.has(n.tagName)) return 'rich';
    }
    return 'text';
  }

  /** Build the top frame line — used by both modes. */
  function buildTopFrame(title, totalWidth) {
    const visibleTitleLen = FRAME_TITLE_OVERHEAD + title.length;
    const dashCount = Math.max(0, totalWidth - visibleTitleLen - 1);
    return `╔═<span class="x">■</span>══[ <span class="t">${escapeHtml(title)}</span> ]${'═'.repeat(dashCount)}╗`;
  }

  function buildBottomFrame(totalWidth) {
    return `╚${'═'.repeat(totalWidth - 2)}╝`;
  }

  /** Render one window section. */
  function renderWindow(section, charPx) {
    const sourceContent = section.querySelector('.window-content');
    if (!section.dataset.frameTitle) {
      section.dataset.frameTitle = section.dataset.title || '';
    }
    if (!section.dataset.windowMode) {
      if (!sourceContent) return;
      section.dataset.windowMode = autoDetectMode(sourceContent);
    }
    if (section.dataset.windowMode === 'text' && !section.dataset.frameSrc) {
      if (!sourceContent) return;
      section.dataset.frameSrc = sourceContent.innerHTML;
    }
    const title = section.dataset.frameTitle;
    const mode = section.dataset.windowMode;

    // Compute total frame width in chars from the section's parent width.
    const containerWidth = section.parentElement.getBoundingClientRect().width;
    const maxCols = Math.max(20, Math.floor(containerWidth / charPx));
    const totalWidth = Math.min(maxCols, 100);
    const textWidth = totalWidth - SIDE_OVERHEAD;

    const top = buildTopFrame(title, totalWidth);
    const bottom = buildBottomFrame(totalWidth);
    const expCls = section.dataset.experiment !== undefined ? ' experiment' : '';

    if (mode === 'rich') {
      const w = `${totalWidth}ch`;
      let topFrame = section.querySelector(':scope > .ansi-window-top');
      let body = section.querySelector(':scope > .ansi-window-body');
      let bottomFrame = section.querySelector(':scope > .ansi-window-bot');

      if (!topFrame || !body || !bottomFrame) {
        const content = sourceContent;
        if (!content) return;

        topFrame = document.createElement('pre');
        body = document.createElement('div');
        bottomFrame = document.createElement('pre');

        while (content.firstChild) {
          body.appendChild(content.firstChild);
        }

        section.replaceChildren(topFrame, body, bottomFrame);
      }

      topFrame.className = `ansi-window-frame ansi-window-top${expCls}`;
      body.className = `ansi-window-body${expCls}`;
      bottomFrame.className = `ansi-window-frame ansi-window-bot${expCls}`;
      topFrame.style.width = w;
      body.style.width = w;
      bottomFrame.style.width = w;
      topFrame.innerHTML = top;
      bottomFrame.innerHTML = bottom;
      section.classList.add('window-rich');
      section.classList.remove('window-text');
      return;
    }

    // text mode: word-wrap every paragraph into ║ … ║ rows.
    const tmp = document.createElement('div');
    tmp.innerHTML = section.dataset.frameSrc;
    const blocks = [];
    for (const node of tmp.children) {
      if (node.tagName === 'P') {
        blocks.push(wrapHtmlLine(node.innerHTML, textWidth));
      } else if (node.tagName === 'HR') {
        blocks.push([{ markup: '─'.repeat(textWidth), visible: textWidth }]);
      }
    }

    const blank = `║${' '.repeat(totalWidth - 2)}║`;
    const rows = [top, blank];
    for (let i = 0; i < blocks.length; i++) {
      for (const ln of blocks[i]) {
        const pad = ' '.repeat(Math.max(0, textWidth - ln.visible));
        rows.push(`║  ${ln.markup}${pad}  ║`);
      }
      if (i < blocks.length - 1) rows.push(blank);
    }
    rows.push(blank, bottom);

    section.innerHTML = `<pre class="ansi-window${expCls}">${rows.join('\n')}</pre>`;
    section.classList.add('window-text');
    section.classList.remove('window-rich');
  }

  function renderAll() {
    const sections = document.querySelectorAll('.window[data-title]');
    if (!sections.length) return;
    const charPx = measureCharWidth(sections[0]);
    sections.forEach(s => renderWindow(s, charPx));
    document.dispatchEvent(new CustomEvent('ansi-windows-rendered'));
  }

  // Re-renders need the original source preserved. The first render caches
  // it in dataset.frameSrc. Subsequent calls (resize) reuse that cache.
  let raf;
  function debouncedRerender() {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(renderAll);
  }

  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(renderAll);
  } else if (document.readyState !== 'loading') {
    renderAll();
  } else {
    document.addEventListener('DOMContentLoaded', renderAll);
  }
  window.addEventListener('resize', debouncedRerender);
})();
