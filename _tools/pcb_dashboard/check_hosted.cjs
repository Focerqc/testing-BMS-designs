const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const site = path.resolve(__dirname, '../../site');
const snapshot = JSON.parse(fs.readFileSync(path.join(site, 'data/dashboard.json')));
const storage = new Map();
const context = {window: {}, URL, Response, location: {href: 'https://example.com/testing-BMS-designs/'}, fetch: async () => new Response(JSON.stringify(snapshot)), localStorage: {getItem: k => storage.get(k), setItem: (k,v) => storage.set(k,v)}, document: {addEventListener: () => {}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(site, 'hosted.js'), 'utf8'), context);
(async () => {
 const request = async (endpoint, options) => (await context.window.dashboardFetch(endpoint, options)).json();
 const boards = await request('/api/boards');
 assert.ok(boards.length >= 1, 'at least one board published');
 for (const board of boards) {
  const query = '?path=' + encodeURIComponent(board);
  assert.equal((await request('/api/board' + query)).path, board);
  assert.equal((await request('/api/render_status' + query)).top.exists, true);
  const sch = await request('/api/render_full_schematic' + query);
  assert.equal(sch.status, 'ok', board + ' schematic');
  assert.ok(fs.existsSync(path.join(site, sch.pdf)), sch.pdf);
  await request('/api/boxes' + query, {method: 'POST', body: JSON.stringify({colors: [{id:'test'}]})});
  assert.equal((await request('/api/boxes' + query)).colors[0].id, 'test');
 }
 for (const asset of Object.values(snapshot.assets)) assert.ok(fs.existsSync(path.join(site, asset)), asset);
 for (const file of ['news.html', 'news.css']) assert.ok(fs.existsSync(path.join(site, file)), file);
 assert.ok(!fs.readFileSync(path.join(site, 'app.js'), 'utf8').includes('`/api/image'));
 const page = fs.readFileSync(path.join(site, 'index.html'), 'utf8');
 assert.ok(page.includes('href="news.html"'));
 for (const file of ['style.css', 'hosted.js', 'app.js']) {
  const digest = require('node:crypto').createHash('sha256').update(fs.readFileSync(path.join(site, file))).digest('hex').slice(0, 10);
  assert.ok(page.includes(`"${file}?v=${digest}"`), `index.html must load ${file}?v=${digest} (re-run export_site.py)`);
 }
 assert.ok(!JSON.stringify(snapshot).includes('racc'), 'private racc folder must not be published');
 console.log('Passed: board snapshots, renders, schematics, browser saves, assets, News, hashed script/style URLs, no private files.');
})();
