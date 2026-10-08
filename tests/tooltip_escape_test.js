#!/usr/bin/env node
/**
 * Regression check (LC-03): crawled page titles and URLs must reach the site-structure
 * tooltip as text, never as markup.
 *
 * Loads the real web/static/js/visualization.js in a Node VM with a minimal DOM and a
 * Cytoscape stub, fires the node mouseover handler, and inspects the tooltip HTML.
 *
 *   node tests/tooltip_escape_test.js
 *
 * Prints PASS/FAIL per check and exits non-zero if any check fails.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SCRIPT = path.join(__dirname, '..', 'web', 'static', 'js', 'visualization.js');

function loadVisualization() {
  const handlers = {};
  let lastAppended = null;
  const cy = new Proxy(function () {}, {
    get(target, prop) {
      if (prop === 'on') return (event, selector, handler) => { handlers[event] = handler; return cy; };
      if (prop === Symbol.toPrimitive) return () => '';
      if (prop === 'then') return undefined;
      return cy;
    },
    set() { return true; },
    apply() { return cy; },
  });

  function makeElement(tag) {
    let text = '';
    const element = {
      tagName: tag, style: {}, className: '', innerHTML: '', children: [],
      appendChild(child) { this.children.push(child); return child; },
      querySelector() { return null; },
      classList: { add() {}, remove() {} },
      addEventListener() {},
    };
    // Like a browser: text assigned through textContent is serialised into innerHTML, escaped
    Object.defineProperty(element, 'textContent', {
      get() { return text; },
      set(value) {
        text = String(value);
        element.innerHTML = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      },
    });
    return element;
  }

  const elements = {};
  const document = {
    getElementById(id) { return elements[id] || (elements[id] = makeElement('div')); },
    createElement: makeElement,
    body: { appendChild(child) { lastAppended = child; return child; } },
    querySelectorAll() { return []; },
    addEventListener() {},
  };
  const context = {
    document,
    console,
    window: { addEventListener() {} },
    cytoscape: () => cy,
    fetch: () => new Promise(() => {}),
    setTimeout, clearTimeout,
    setInterval: () => 0, clearInterval() {},
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(SCRIPT, 'utf8'), context, { filename: SCRIPT });
  context.initVisualization();

  return {
    hoverNode(data) {
      handlers.mouseover({ target: { data: () => data } });
      return lastAppended ? lastAppended.innerHTML : null;
    },
  };
}

const checks = [
  {
    name: 'entity-encoded title is shown as text, not markup',
    node: { url: 'https://example.test/page', title: '<img src=x onerror="alert(document.domain)">', status_code: 200 },
    verify(html) {
      return !html.includes('<img') && html.includes('&lt;img');
    },
  },
  {
    name: 'markup in the URL is escaped',
    node: { url: 'https://example.test/"><script>alert(1)</script>', title: 'Home', status_code: 200 },
    verify(html) {
      return !html.includes('<script') && html.includes('&lt;script');
    },
  },
  {
    name: 'ordinary titles still render',
    node: { url: 'https://example.test/', title: 'Pricing & plans', status_code: 200 },
    verify(html) {
      return html.includes('Pricing &amp; plans');
    },
  },
];

let failed = 0;
for (const check of checks) {
  let ok = false;
  try {
    const html = loadVisualization().hoverNode(check.node);
    ok = html !== null && check.verify(html);
  } catch (err) {
    console.log(`  error: ${err.message}`);
  }
  console.log(`${ok ? 'PASS' : 'FAIL'} ${check.name}`);
  if (!ok) failed += 1;
}
console.log(failed ? `${failed} check(s) failed` : 'all checks passed');
process.exit(failed ? 1 : 0);
