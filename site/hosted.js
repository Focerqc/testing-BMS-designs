// Transport for the shared Board Boxes UI on static GitHub Pages hosting.
(() => {
  let snapshot;
  // no-cache: ask Pages each load (a 304 if unchanged), so the snapshot is never older than app.js.
  const ready = fetch('data/dashboard.json', { cache: 'no-cache' }).then(r => {
    if (!r.ok) throw new Error('Published board snapshot unavailable');
    return r.json();
  }).then(data => (snapshot = data));
  window.dashboardAsset = path => snapshot.assets[path] || '';
  window.dashboardSchematic = path => snapshot.boards[path]?.schematic?.pdf || '';
  window.dashboardFetch = async (input, options = {}) => {
    const data = await ready;
    const url = new URL(input, location.href);
    const endpoint = url.pathname.split('/').pop();
    const path = url.searchParams.get('path');
    const item = data.boards[path];
    const key = 'bms-designs-hosted-boxes-v1:' + path;
    let result;
    switch (endpoint) {
      case 'boards': result = Object.keys(data.boards); break;
      case 'images': result = data.images; break;
      case 'board': result = item?.board; break;
      case 'boxes':
        if (options.method === 'POST') {
          localStorage.setItem(key, options.body);
          result = {status: 'ok', file: 'browser'};
        } else {
          const saved = localStorage.getItem(key);
          result = saved ? {...JSON.parse(saved), exists: true} : item?.boxes;
        }
        break;
      case 'render_status': result = item?.renders; break;
      case 'render_schematic':
      case 'render_full_schematic': result = item?.schematic ? {status: 'ok', ...item.schematic} : {error: 'No schematic published for this board'}; break;
      case 'render_3d': result = {error: 'Fresh renders require the local KiCad dashboard. This site displays published renders.'}; break;
      default: result = {error: 'Unsupported hosted operation'};
    }
    return new Response(JSON.stringify(result || {error: 'Board not in published snapshot'}), {headers: {'Content-Type': 'application/json'}});
  };
  document.addEventListener('DOMContentLoaded', () => {
    for (const id of ['btnTopRender3D', 'btnIsoRender3D']) {
      const button = document.getElementById(id);
      button.disabled = true;
      button.title = 'Generate fresh renders in the local KiCad dashboard, then publish the snapshot.';
    }
  });
})();
