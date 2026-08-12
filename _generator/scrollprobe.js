// Drives a real Chrome over CDP: navigates, scrolls for real, waits for the page's own
// rAF to settle, and reads geometry back. Exists because --virtual-time-budget does not
// tick requestAnimationFrame, so any scroll-driven effect measured that way reads as frozen.
const [,, url, sel, ...ys] = process.argv;
const scrolls = (ys.length ? ys : ['0','400','800','1200','1600','2000']).map(Number);

const http = require('http');
// /json/new requires PUT, not GET — Chrome rejects the GET with a plain-text error.
const req = (p, method='GET') => new Promise(r => {
  const rq = http.request({host:'127.0.0.1',port:9333,path:p,method},
    res => { let d=''; res.on('data',c=>d+=c); res.on('end',()=>r(JSON.parse(d))); });
  rq.end();
});

(async () => {
  const tab = await req('/json/new?' + encodeURIComponent(url), 'PUT');
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  let id = 0; const pend = new Map();
  const send = (method, params={}) => new Promise(res => { pend.set(++id, res);
    ws.send(JSON.stringify({id, method, params})); });
  ws.onmessage = e => { const m = JSON.parse(e.data);
    if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id); } };
  await new Promise(r => ws.onopen = r);

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride',
             {width:1400, height:800, deviceScaleFactor:1, mobile:false});
  await new Promise(r => setTimeout(r, 1800));   // let media and rasters land

  const evalJS = async expr => (await send('Runtime.evaluate',
      {expression: expr, returnByValue: true, awaitPromise: true})).result.value;

  console.log('scrollY\ttransformY\telTop\tcardTop\td(el)/d(scroll)');
  let prev = null;
  for (const y of scrolls) {
    await evalJS(`new Promise(r=>{scrollTo(0,${y});
      requestAnimationFrame(()=>requestAnimationFrame(()=>r(1)))})`);
    const o = await evalJS(`(()=>{const e=document.querySelector('${sel}');
      if(!e) return null;
      const m=new DOMMatrixReadOnly(getComputedStyle(e).transform);
      const r=e.getBoundingClientRect();
      const p=e.parentNode.getBoundingClientRect();
      return {ty:Math.round(m.m42), top:Math.round(r.top), ptop:Math.round(p.top),
              fill:getComputedStyle(e.parentNode).getPropertyValue('--fill').trim()};})()`);
    if (!o) { console.log('selector not found'); break; }
    const rate = prev ? ((o.top - prev.top) / (y - prev.y)).toFixed(2) : '-';
    console.log([y, o.ty, o.top, o.ptop, rate].join('\t') + (o.fill ? `\t--fill=${o.fill}` : ''));
    prev = {y, top:o.top};
  }
  ws.close(); process.exit(0);
})();
