// Visits every page of the running demo in headless Chrome/Edge at desktop and mobile sizes.
// Reports console errors, failed network requests (any request that leaves the page is a failure in demo mode),
// horizontal overflow and empty pages, and saves screenshots.
//   node scripts/browser-check.mjs [baseUrl] [outDir]      (default http://127.0.0.1:3000, ./.shots)
// Needs no packages: it talks to the browser over the DevTools protocol using Node's built-in WebSocket.
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const BASE = process.argv[2] || 'http://127.0.0.1:3000';
const OUT = process.argv[3] || '.shots';
const BROWSERS = [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
];
const exe = BROWSERS.find(existsSync);
if (!exe) { console.error('No Chrome or Edge found'); process.exit(2); }

const ROUTES = [
  '/', '/articles', '/articles/1', '/topics', '/publishing', '/analytics', '/automation',
  '/shipping', '/shipping?tab=shipments', '/shipping?tab=checks', '/shipping?tab=analytics',
  '/settings/integrations', '/settings/brands', '/settings/data', '/settings/audit',
];
const SIZES = [['desktop', 1440, 900, false], ['tablet', 820, 1100, true], ['mobile', 390, 844, true]];
mkdirSync(OUT, { recursive: true });

const port = 9300 + Math.floor(Math.random() * 500);
const profile = mkdtempSync(join(tmpdir(), 'flowmerce-chrome-'));
const proc = spawn(exe, [`--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, '--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function target() {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      const page = list.find((t) => t.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* not up yet */ }
    await sleep(250);
  }
  throw new Error('browser did not start');
}

const ws = new WebSocket(await target());
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
let id = 0;
const pending = new Map();
const events = [];
ws.addEventListener('message', (m) => {
  const msg = JSON.parse(m.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); } else events.push(msg);
});
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expr) => (await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })).result?.result?.value;

await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable'); await send('Log.enable');
const problems = [];
const origin = new URL(BASE).origin;

for (const [name, w, h, mobile] of SIZES) {
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile });
  for (const route of ROUTES) {
    events.length = 0;
    await send('Page.navigate', { url: BASE + route });
    await sleep(2600);
    const issues = [];
    for (const e of events) {
      if (e.method === 'Runtime.exceptionThrown') issues.push(`exception: ${e.params.exceptionDetails.exception?.description?.split('\n')[0] ?? e.params.exceptionDetails.text}`);
      if (e.method === 'Runtime.consoleAPICalled' && e.params.type === 'error') issues.push(`console.error: ${e.params.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 200)}`);
      if (e.method === 'Network.requestWillBeSent') {
        const u = e.params.request.url;
        if (!u.startsWith(origin) && !u.startsWith('data:') && !u.startsWith('blob:') && !/fonts\.(googleapis|gstatic)\.com/.test(u)) issues.push(`external request: ${u}`);
        if (u.startsWith(`${origin}/api/`)) issues.push(`network /api request: ${u}`);
      }
    }
    const m = await ev(`(() => { const d = document.documentElement; const main = document.querySelector('main'); return { overflow: d.scrollWidth - d.clientWidth, text: (main?.innerText ?? '').trim().length, h1: document.querySelector('h1')?.innerText ?? '', crit: [...document.querySelectorAll('.callout.crit')].filter((x) => x.innerText.includes('Could not load')).map((x) => x.innerText.slice(0, 120)) }; })()`);
    if (!m) issues.push('page did not evaluate');
    else {
      if (m.overflow > 1) issues.push(`horizontal overflow ${m.overflow}px`);
      if (m.text < 40) issues.push('page is nearly empty');
      for (const c of m.crit) issues.push(`error callout: ${c}`);
    }
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    const file = join(OUT, `${name}${route.replace(/[^a-z0-9]+/gi, '_')}.png`);
    writeFileSync(file, Buffer.from(shot.result.data, 'base64'));
    console.log(`${issues.length ? 'FAIL' : 'ok  '} ${name.padEnd(7)} ${route.padEnd(32)} ${m?.h1 ?? ''}${issues.length ? '\n       ' + issues.join('\n       ') : ''}`);
    if (issues.length) problems.push([name, route, issues]);
  }
}
ws.close(); proc.kill();
console.log(problems.length ? `\n${problems.length} page(s) with problems` : '\nAll pages clean');
process.exit(problems.length ? 1 : 0);
