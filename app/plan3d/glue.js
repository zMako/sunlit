// glue.js: apartment.html -> checkout. Adds a "Checkout" link and the running furniture total (sum of saved plan totals) to the
// top panel. Rooms with a plan = GET /api/furnish?room=<unit>__<rid> returns 200. Standalone: reads the layout itself, touches
// nothing else on the page except chaining window.furnishOnChange (agent.js calls it after a furnishing run).
const Q = new URLSearchParams(location.search); const unit = Q.get('unit');
const ui = document.getElementById('ui');
if (unit && ui) {
  const st = document.createElement('style');
  st.textContent = `#coRow{margin-top:8px;padding-top:8px;border-top:1px solid #243040;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
#coBtn{background:#7fe0b4;color:#07111f;border:none;border-radius:8px;padding:6px 12px;font-weight:700;text-decoration:none;font-size:13px}
#coBtn.off{background:#2a3444;color:#9aa4b2;pointer-events:none}#coTot{color:#cbd5e1;font-size:12px}#coBack{color:#93c5fd;font-size:12px;text-decoration:none}`;
  document.head.appendChild(st);
  const row = document.createElement('div'); row.id = 'coRow';
  row.innerHTML = `<a id="coBtn" class="off" target="_blank" href="#">Checkout</a><span id="coTot">checking plans…</span><a id="coBack" href="index.html">all units</a>`;
  ui.appendChild(row);
  const btn = row.querySelector('#coBtn'), tot = row.querySelector('#coTot');
  let roomIds = null, busy = false;
  const movein = () => new Date(Date.now() + 21 * 864e5).toISOString().slice(0, 10);
  const budget = () => { const b = document.getElementById('aiBudget'); const v = b ? +b.value : 0; return v > 0 ? v : 3500; };
  async function refresh() {
    if (busy) return; busy = true;
    try {
      if (!roomIds) { const L = await (await fetch(`layouts/${unit}.json`)).json(); roomIds = L.rooms.map(r => r.id); }
      const res = await Promise.all(roomIds.map(async rid => { const room = `${unit}__${rid}`;
        try { const r = await fetch(`/api/furnish?room=${encodeURIComponent(room)}`, { cache: 'no-store' }); if (r.status !== 200) return null;
          const p = await r.json(); const items = (p.items || []).filter(i => i.category !== 'fixture');
          const t = items.reduce((s, i) => s + (+i.price_usd || 0), 0);
          return { room, total: t, n: items.length }; } catch (e) { return null; } }));
      const ok = res.filter(Boolean); const sum = ok.reduce((s, r) => s + r.total, 0), n = ok.reduce((s, r) => s + r.n, 0);
      const href = `../checkout/checkout.html?rooms=${ok.map(r => r.room).join(',')}&budget=${budget()}&movein=${movein()}`;
      btn.href = href; btn.dataset.rooms = ok.map(r => r.room).join(',');
      btn.classList.toggle('off', ok.length === 0);
      tot.textContent = ok.length ? `$${sum.toLocaleString(undefined, { maximumFractionDigits: 0 })} · ${n} items in ${ok.length} room${ok.length > 1 ? 's' : ''}` : 'no furnishing plan yet: furnish a room first';
    } finally { busy = false; }
  }
  btn.addEventListener('click', () => { const u = new URL(btn.href, location.href); u.searchParams.set('budget', budget()); btn.href = u.pathname + u.search; });
  const prev = window.furnishOnChange; window.furnishOnChange = (...a) => { try { prev && prev(...a); } finally { refresh(); } };
  document.addEventListener('change', e => { if (e.target && e.target.id === 'aiBudget') refresh(); });
  refresh(); setInterval(() => { if (!document.hidden) refresh(); }, 10000);
  window.sunlitCheckoutRefresh = refresh;
}
