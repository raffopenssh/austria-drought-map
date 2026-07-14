/* GW Power — frontend app. One choropleth (Groundwater Status Index per
 * Gemeinde, KG-resolved on tap), subtle station dots, KG detail modal,
 * station timelines, cadastre-backed search, shareable URLs. */
'use strict';

// ---------- config ----------
const CADASTRE = 'https://cadastre-process-api.exe.xyz';
const GRAD = [
    [0.00, [0x1a, 0x98, 0x50]],
    [0.20, [0x91, 0xcf, 0x60]],
    [0.40, [0xd9, 0xef, 0x8b]],
    [0.55, [0xfe, 0xe0, 0x8b]],
    [0.75, [0xfc, 0x8d, 0x59]],
    [1.00, [0xd7, 0x30, 0x27]],
];
const CAT_COLOR = { good: '#7ed37e', watch: '#f5cf6b', stressed: '#f28a7d' };
const COMPONENTS = [ // [key in gwi record, label, weight, raw key, raw formatter]
    ['q_trend',   'Level trend',        0.35, 'gw_trend', v => (v > 0 ? '+' : '') + (v * 100).toFixed(0) + ' cm/dec'],
    ['q_div',     'Precip divergence',  0.15, 'gw_div',   v => v.toFixed(2) + ' σ'],
    ['q_nitrate', 'Nitrate',            0.25, 'no3',      v => v.toFixed(1) + ' mg/L'],
    ['q_wfd',     'WFD status risk',    0.10, null,       null],
    ['q_edo',     'Drought pressure',   0.15, null,       null],
];

// ---------- state ----------
let map, choroLayer, gwLayerGroup, no3LayerGroup;
let gwiKG = null;          // gw_index_kg.json .kgs
let gwiMeta = null;
let kgReg = null;          // kg_registry.json
let gwStations = [];       // slim
let plantInfl = null;      // plant_influence.json (hydropower downstream impact)
let no3Stations = [];      // nitrate stations
let muniByIso = {}, muniByName = {};
let gwTrendsCache = null;  // lazy full annual data
let chart = null;          // active Chart.js instance
let currentShare = {};     // extra params beyond view
let kgRegList = null;      // [[code, rec], ...] cached array

const $ = id => document.getElementById(id);

function gwiColor(v) {
    if (v == null || isNaN(v)) return '#3a3f55';
    v = Math.max(0, Math.min(1, v));
    for (let i = 1; i < GRAD.length; i++) {
        if (v <= GRAD[i][0]) {
            const [p0, c0] = GRAD[i - 1], [p1, c1] = GRAD[i];
            const t = (v - p0) / (p1 - p0);
            const c = c0.map((a, j) => Math.round(a + t * (c1[j] - a)));
            return `rgb(${c[0]},${c[1]},${c[2]})`;
        }
    }
    return '#d73027';
}

function distKm(lat1, lon1, lat2, lon2) {
    const x = (lon2 - lon1) * Math.cos((lat1 + lat2) * Math.PI / 360) * 111.32;
    const y = (lat2 - lat1) * 110.57;
    return Math.sqrt(x * x + y * y);
}

function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

// ---------- boot ----------
async function boot() {
    map = L.map('map', {
        zoomControl: true, preferCanvas: true,
        center: [47.6, 13.5], zoom: 7, minZoom: 6, maxZoom: 18,
        zoomSnap: 0.5, attributionControl: true,
    });
    map.zoomControl.setPosition('bottomleft');
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OSM &copy; CARTO', subdomains: 'abcd', maxZoom: 19,
    }).addTo(map);

    const [geo, slim, no3, gwi, reg, munis, pinf] = await Promise.all([
        fetch('data/municipalities_risk.geojson').then(r => r.json()),
        fetch('data/gw_stations_slim.json').then(r => r.json()),
        fetch('data/nitrate_stations.json').then(r => r.json()),
        fetch('data/gw_index_kg.json').then(r => r.json()),
        fetch('data/kg_registry.json').then(r => r.json()),
        fetch('data/municipalities.json').then(r => r.json()),
        fetch('data/plant_influence.json').then(r => r.json()).catch(() => null),
    ]);
    plantInfl = pinf;
    gwiKG = gwi.kgs; gwiMeta = gwi; kgReg = reg;
    kgRegList = Object.entries(reg);
    gwStations = slim.filter(s => s.lat && s.lon);
    no3Stations = (no3.stations || []).filter(s => s.lat && s.lon);
    for (const m of munis) {
        muniByIso[String(m.iso)] = m;
        muniByName[String(m.name).toLowerCase()] = m;
    }

    buildChoropleth(geo);
    buildStationLayers();
    wireUI();
    restoreFromURL();
    $('loading-overlay').style.display = 'none';
}

// ---------- choropleth ----------
function buildChoropleth(geo) {
    choroLayer = L.geoJSON(geo, {
        style: f => ({
            fillColor: gwiColor(f.properties.gwi),
            fillOpacity: 0.55,
            color: '#0d1022', weight: 0.5, opacity: 0.6,
        }),
        onEachFeature: (f, layer) => {
            const p = f.properties;
            const g = p.gwi != null ? p.gwi.toFixed(2) : '–';
            const cat = p.gwi_category || 'no data';
            layer.bindTooltip(
                `<b>${esc(p.name)}</b><br>GWI ${g} · <span style="color:${CAT_COLOR[cat] || '#8b93b8'}">${cat}</span>`,
                { className: 'gw-tip', sticky: true });
            layer.on('mouseover', () => layer.setStyle({ weight: 1.6, color: '#4fc3f7', opacity: 1 }));
            layer.on('mouseout', () => choroLayer.resetStyle(layer));
            layer.on('click', e => {
                L.DomEvent.stop(e);
                openKGAt(e.latlng.lat, e.latlng.lng);
            });
        },
    }).addTo(map);
    map.on('click', e => openKGAt(e.latlng.lat, e.latlng.lng));
}

// ---------- station dots ----------
function trendTint(t) {
    if (t == null) return '#5a6a9a';
    return t < -0.1 ? '#c98a9a' : t > 0.1 ? '#7ec8e0' : '#7a8ac0';
}
function no3Tint(v) {
    if (v == null) return '#6a6a8a';
    return v >= 50 ? '#e06a6a' : v >= 25 ? '#d0a860' : '#7a9ac0';
}
function dotStyle() {
    const z = map.getZoom();
    return {
        radius: z <= 7 ? 1.2 : z <= 9 ? 2 : z <= 11 ? 3 : 4.5,
        fillOpacity: z <= 7 ? 0.35 : z <= 9 ? 0.55 : 0.75,
        weight: z <= 8 ? 0 : 0.8,
    };
}
function buildStationLayers() {
    const rnd = L.canvas({ padding: 0.4 });
    const ds = dotStyle();
    gwLayerGroup = L.layerGroup();
    for (const s of gwStations) {
        const m = L.circleMarker([s.lat, s.lon], {
            renderer: rnd, radius: ds.radius, weight: ds.weight,
            color: 'rgba(10,14,30,0.7)',
            fillColor: trendTint(s.trend_m_per_decade), fillOpacity: ds.fillOpacity,
        });
        m.on('click', e => { L.DomEvent.stop(e); openGWStation(s); });
        m.bindTooltip(() => `<b>${esc(s.name)}</b><br>trend ${s.trend_m_per_decade != null ? (s.trend_m_per_decade * 100).toFixed(0) + ' cm/dec' : '–'}`,
            { className: 'gw-tip' });
        gwLayerGroup.addLayer(m);
    }
    no3LayerGroup = L.layerGroup();
    for (const s of no3Stations) {
        const m = L.circleMarker([s.lat, s.lon], {
            renderer: rnd, radius: ds.radius, weight: ds.weight,
            color: 'rgba(10,14,30,0.7)',
            fillColor: no3Tint(s.latest), fillOpacity: ds.fillOpacity,
        });
        m.on('click', e => { L.DomEvent.stop(e); openNO3Station(s); });
        m.bindTooltip(() => `<b>${esc(s.id)}</b><br>${s.latest != null ? s.latest.toFixed(1) + ' mg/L NO₃ (' + s.latest_year + ')' : '–'}`,
            { className: 'gw-tip' });
        no3LayerGroup.addLayer(m);
    }
    map.on('zoomend', () => {
        const d = dotStyle();
        for (const grp of [gwLayerGroup, no3LayerGroup]) {
            grp.eachLayer(m => m.setStyle({ radius: d.radius, fillOpacity: d.fillOpacity, weight: d.weight }));
        }
    });
    gwLayerGroup.addTo(map);
    $('n-gw').textContent = `(${gwStations.length})`;
    $('n-no3').textContent = `(${no3Stations.length})`;
    $('tg-gw').addEventListener('change', e =>
        e.target.checked ? gwLayerGroup.addTo(map) : map.removeLayer(gwLayerGroup));
    $('tg-no3').addEventListener('change', e =>
        e.target.checked ? no3LayerGroup.addTo(map) : map.removeLayer(no3LayerGroup));
}

// ---------- KG resolution (click -> KG) ----------
function bboxCandidates(lat, lon) {
    const out = [];
    for (const [code, r] of kgRegList) {
        const b = r.bb;
        if (b && lon >= b[0] && lat >= b[1] && lon <= b[2] && lat <= b[3]) out.push(code);
    }
    return out;
}
function nearestKG(lat, lon) {
    let best = null, bd = Infinity;
    for (const [code, r] of kgRegList) {
        const d = distKm(lat, lon, r.lat, r.lon);
        if (d < bd) { bd = d; best = code; }
    }
    return best;
}
async function resolveKG(lat, lon) {
    const cand = bboxCandidates(lat, lon);
    if (cand.length === 1) return cand[0];
    try {
        const resp = await fetch(CADASTRE + '/api/v1/spatial/points', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ points: [{ lon, lat }] }),
        });
        const j = await resp.json();
        const r = (j.results || [])[0];
        if (r && r.kg_code) return r.kg_code;
    } catch (e) { /* offline fallback below */ }
    if (cand.length) { // nearest centroid among bbox candidates
        let best = null, bd = Infinity;
        for (const c of cand) {
            const d = distKm(lat, lon, kgReg[c].lat, kgReg[c].lon);
            if (d < bd) { bd = d; best = c; }
        }
        return best;
    }
    return nearestKG(lat, lon);
}
async function openKGAt(lat, lon) {
    const body = $('kg-modal-body');
    body.innerHTML = '<div style="text-align:center;padding:60px 0;"><div class="loading-spinner" style="margin:0 auto 12px;"></div><span style="color:#6a7194;">Resolving Katastralgemeinde…</span></div>';
    openModal('kg-modal');
    const code = await resolveKG(lat, lon);
    if (!code) { body.innerHTML = '<p>Could not resolve a Katastralgemeinde here.</p>'; return; }
    showKGModal(code);
}

// ---------- KG modal ----------
function compBarsHTML(rec) {
    let html = '';
    for (const [key, label, w, rawKey, fmt] of COMPONENTS) {
        const v = rec[key];
        const raw = rawKey && rec[rawKey] != null && fmt ? fmt(rec[rawKey]) : '';
        const pct = v != null ? Math.round(v * 100) : 0;
        html += `<div class="comp-row">
            <div class="comp-label">${label} <small>·&nbsp;w ${Math.round(w * 100)}%</small></div>
            <div class="comp-bar"><div class="comp-fill" style="width:${pct}%;background:${v != null ? gwiColor(v) : '#3a3f55'}"></div></div>
            <div class="comp-val">${v != null ? v.toFixed(2) : 'n/a'}${raw ? `<br><small style="color:#6a7194">${raw}</small>` : ''}</div>
        </div>`;
    }
    return html;
}
function edoBarsHTML(muni) {
    if (!muni || !muni.edo_yearly) return '';
    const bars = Object.entries(muni.edo_yearly).map(([yr, v]) => {
        const h = Math.max(4, Math.min(100, (v.mean / 2) * 100));
        const col = v.mean > 1.2 ? '#e94560' : v.mean > 0.8 ? '#f97316' : v.mean > 0.4 ? '#f39c12' : '#3b82f6';
        return `<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:2px;" title="${yr}: mean CDI ${v.mean.toFixed(2)}, max ${v.max.toFixed(1)}">
            <div style="width:100%;height:${h}%;background:${col};border-radius:2px 2px 0 0;min-height:2px;"></div>
            <span style="font-size:0.55em;color:#6a7194;">${yr.slice(2)}</span></div>`;
    }).join('');
    return `<h3>Drought history (EDO CDI)</h3>
        <div class="edo-bars">${bars}</div>
        <div class="note">Bar = yearly mean Combined Drought Indicator of the Gemeinde (0 none … 3+ alert). Source: Copernicus EDO.</div>`;
}
function stationListHTML(lat, lon, radiusKm) {
    const near = t => t
        .map(s => ({ s, d: distKm(lat, lon, s.lat, s.lon) }))
        .filter(x => x.d <= radiusKm)
        .sort((a, b) => a.d - b.d).slice(0, 8);
    const gws = near(gwStations);
    const n3s = near(no3Stations);
    let html = '';
    if (gws.length) {
        html += `<h3>Groundwater level stations <small style="color:#6a7194;font-weight:400">≤ ${radiusKm} km</small></h3><div class="station-list">` +
            gws.map(({ s, d }) => {
                const t = s.trend_m_per_decade;
                return `<div class="station-item" onclick="openGWStationById('${esc(s.id)}')">
                    <span class="dot" style="background:${trendTint(t)}"></span>
                    <span class="nm">${esc(s.name)}</span>
                    <span class="meta">${d.toFixed(1)} km</span>
                    <span class="val" style="color:${t != null && t < -0.1 ? '#f28a7d' : t != null && t > 0.1 ? '#7ec8e0' : '#b9c0dd'}">${t != null ? (t > 0 ? '+' : '') + (t * 100).toFixed(0) + ' cm/dec' : '–'}</span>
                </div>`;
            }).join('') + '</div>';
    }
    if (n3s.length) {
        html += `<h3>Nitrate stations <small style="color:#6a7194;font-weight:400">≤ ${radiusKm} km</small></h3><div class="station-list">` +
            n3s.map(({ s, d }) => `<div class="station-item" onclick="openNO3StationById('${esc(s.id)}')">
                    <span class="dot" style="background:${no3Tint(s.latest)}"></span>
                    <span class="nm">${esc(s.id)}</span>
                    <span class="meta">${d.toFixed(1)} km · ${s.latest_year || ''}</span>
                    <span class="val" style="color:${no3Tint(s.latest)}">${s.latest != null ? s.latest.toFixed(1) + ' mg/L' : '–'}</span>
                </div>`).join('') + '</div>';
    }
    if (!html) html = '<p class="note">No monitoring stations within ' + radiusKm + ' km.</p>';
    return html;
}
// ---------- hydropower downstream impact (plant_influence.json) ----------
function hydroLinksForKG(code) {
    if (!plantInfl || !plantInfl.kg_map || !plantInfl.kg_map[code]) return [];
    return plantInfl.kg_map[code].map(i => plantInfl.gw_links_sig[i]).filter(Boolean);
}
function hydroLinksForStation(id) {
    if (!plantInfl || !plantInfl.gw_links_sig) return [];
    return plantInfl.gw_links_sig.filter(l => String(l.station) === String(id));
}
function hydroSparkSVG(l) {
    const sp = l.spark;
    if (!sp || !sp.lvl || sp.lvl.length < 10) return '';
    const W = 260, H = 44, n = sp.lvl.length;
    const pts = a => a.map((v, i) =>
        `${(i / (n - 1) * W).toFixed(1)},${(H - 3 - v / 100 * (H - 8)).toFixed(1)}`).join(' ');
    const d0 = sp.d0.slice(5).replace('-', '/'), d1 = sp.d1.slice(5).replace('-', '/');
    return `<div class="hydro-spark" style="margin:2px 0 6px 20px;">
        <svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="display:block;background:#141a2e;border-radius:6px;">
            <polyline points="${pts(sp.rel)}" fill="none" stroke="#8fb8f2" stroke-width="1" opacity="0.75"/>
            <polyline points="${pts(sp.lvl)}" fill="none" stroke="#facc6b" stroke-width="1.4"/>
        </svg>
        <small style="color:#6a7194;"><span style="color:#facc6b">━</span> well level (${sp.lvl_min}–${sp.lvl_max} m)
        &nbsp;<span style="color:#8fb8f2">━</span> plant release &nbsp;·&nbsp; ${d0}–${d1}</small>
    </div>`;
}
function hydroLinkRowHTML(l, showStation) {
    const p = plantInfl.plants[l.plant] || {};
    const dir = l.beta_sum > 0 ? '↑ level rises with releases' : '↓ level falls with releases';
    const share = Math.round(l.partial * 100);
    return `<div class="station-item" style="cursor:default;display:block;">
        <div style="display:flex;align-items:center;gap:8px;">
        <span class="dot" style="background:#8fb8f2"></span>
        <span class="nm">${esc(p.name || l.plant)} <small style="color:#6a7194">${esc(p.type || '')} · ${p.mw || '?'} MW · ${esc(p.river || '')}</small>${showStation ? `<br><small style="color:#6a7194">at ${esc(l.name)} (<a href="#" onclick="openGWStationById('${esc(l.station)}');return false;">${esc(l.station)}</a>)</small>` : ''}</span>
        <span class="meta">${l.km.toFixed(0)} km downstr.</span>
        <span class="val" title="partial R² = ${l.partial}, p = ${l.p}, placebo = ${l.placebo}">${share}% <small style="color:#6a7194">${dir.slice(0, 1)}</small></span>
        </div>
        ${hydroSparkSVG(l)}
    </div>`;
}
function hydroImpactHTML(links, showStation) {
    if (!links.length) return '';
    const anyDownscaled = links.some(l => (plantInfl.plants[l.plant] || {}).release_source !== 'a73');
    return `<h3>Hydropower influence <small style="color:#6a7194;font-weight:400">detected downstream signal</small></h3>
        <div class="station-list" style="max-height:340px;">${links.map(l => hydroLinkRowHTML(l, showStation)).join('')}</div>
        <div class="note">% = share of day-to-day groundwater level variation at the monitoring well explained by the plant's
        turbined releases (ENTSO-E${anyDownscaled ? ', partly downscaled from the national feed by plant type & capacity' : ' per-unit data'}),
        after controlling for local precipitation. Only links passing significance tests (p&lt;0.01, above placebo) are shown.
        Station and plant are connected along the actual river network. ↑/↓ = level response to releases.
        <b>Correlation, not proven causation.</b> <a href="#" onclick="showMethods();return false;">Details</a></div>`;
}

function gemForKG(reg) {
    if (!reg) return null;
    if (muniByIso[reg.g]) return muniByIso[reg.g];
    // e.g. Vienna: registry says 90001 but municipalities.json has districts.
    let best = null, bd = 12;
    for (const iso in muniByIso) {
        const m = muniByIso[iso];
        const d = distKm(reg.lat, reg.lon, m.lat, m.lon);
        if (d < bd) { bd = d; best = m; }
    }
    return best;
}
function showKGModal(code, opts = {}) {
    const reg = kgReg[code];
    const rec = gwiKG[code] || {};
    const gem = gemForKG(reg);
    const lat = reg ? reg.lat : null, lon = reg ? reg.lon : null;
    const cat = rec.c || 'no data';
    const body = $('kg-modal-body');
    body.innerHTML = `
        <h2>${esc(reg ? reg.n : code)}</h2>
        <div class="subtitle">Katastralgemeinde ${esc(code)}${gem ? ` · Gemeinde ${esc(gem.name)} (${esc(String(gem.iso))})` : ''}</div>
        <div style="display:flex;align-items:center;gap:12px;margin:6px 0 4px;">
            <span style="font-size:2em;font-weight:800;color:${gwiColor(rec.i)}">${rec.i != null ? rec.i.toFixed(2) : '–'}</span>
            <span class="badge ${cat}">${cat}</span>
            ${rec.est ? '<span class="note" title="At least one component interpolated from stations beyond the primary 12.5 km radius">◌ estimated</span>' : ''}
        </div>
        <div class="note">Groundwater Status Index 0 (good) → 1 (stressed). <a href="#" onclick="showMethods();return false;">How it's computed</a></div>
        <h3>Components</h3>
        ${compBarsHTML(rec)}
        <div class="kv-grid" style="margin-top:10px;">
            <div class="kv"><div class="k">GW stations used</div><div class="v">${rec.n_gw ?? '–'}</div></div>
            <div class="kv"><div class="k">Nitrate stations used</div><div class="v">${rec.n_no3 ?? '–'}</div></div>
            ${rec.no3 != null ? `<div class="kv"><div class="k">Nitrate (interp.)</div><div class="v" style="color:${no3Tint(rec.no3)}">${rec.no3.toFixed(1)} mg/L</div></div>` : ''}
            ${rec.gw_trend != null ? `<div class="kv"><div class="k">Level trend (interp.)</div><div class="v" style="color:${trendTint(rec.gw_trend)}">${(rec.gw_trend > 0 ? '+' : '') + (rec.gw_trend * 100).toFixed(0)} cm/dec</div></div>` : ''}
        </div>
        ${edoBarsHTML(gem)}
        ${hydroImpactHTML(hydroLinksForKG(code), true)}
        ${lat != null ? stationListHTML(lat, lon, 12.5) : ''}
        <div class="apirow">API: <code><a href="/llm/kg/${esc(code)}" target="_blank">/llm/kg/${esc(code)}</a></code></div>`;
    openModal('kg-modal');
    currentShare = { kg: code };
    updateURL();
    if (!opts.noFly && lat != null && !map.getBounds().contains([lat, lon])) {
        map.flyTo([lat, lon], Math.max(map.getZoom(), 11), { duration: 0.8 });
    }
}

// ---------- station modals ----------
function destroyChart() { if (chart) { chart.destroy(); chart = null; } }
function closeModal(id) {
    $(id).classList.remove('active');
    if (id === 'st-modal' || id === 'kg-modal') { destroyChart(); currentShare = {}; updateURL(); }
}
function openModal(id) { $(id).classList.add('active'); }
document.querySelectorAll('.modal-overlay').forEach(ov =>
    ov.addEventListener('click', e => { if (e.target === ov) closeModal(ov.id); }));
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') document.querySelectorAll('.modal-overlay.active').forEach(ov => closeModal(ov.id));
});

function openGWStationById(id) { const s = gwStations.find(x => String(x.id) === String(id)); if (s) openGWStation(s); }
function openNO3StationById(id) { const s = no3Stations.find(x => String(x.id) === String(id)); if (s) openNO3Station(s); }

function openGWStation(s) {
    destroyChart();
    const t = s.trend_m_per_decade;
    const status = t == null ? '–' : t < -0.05 ? 'Declining' : t > 0.05 ? 'Rising' : 'Stable';
    const body = $('st-modal-body');
    body.innerHTML = `
        <h2>${esc(s.name)}</h2>
        <div class="subtitle">eHYD groundwater level station · ID ${esc(s.id)}${s.start_year ? ` · ${s.start_year}–${s.end_year}` : ''}</div>
        <div class="kv-grid">
            <div class="kv"><div class="k">10-yr trend</div><div class="v" style="color:${trendTint(t)}">${t != null ? (t > 0 ? '+' : '') + (t * 100).toFixed(1) + ' cm/dec' : '–'}</div></div>
            <div class="kv"><div class="k">Status</div><div class="v">${status}</div></div>
            <div class="kv"><div class="k">p-value (10-yr)</div><div class="v">${s.p_value_10yr != null ? (s.p_value_10yr < 0.001 ? '<0.001' : s.p_value_10yr.toFixed(3)) : (s.p_value != null ? s.p_value.toFixed(3) : '–')}</div></div>
            <div class="kv"><div class="k">Full-period trend</div><div class="v">${s.trend_full_period != null ? (s.trend_full_period * 100).toFixed(1) + ' cm/dec' : '–'}</div></div>
            <div class="kv"><div class="k">Mean level</div><div class="v">${s.mean_level != null ? s.mean_level.toFixed(2) + ' m' : '–'}</div></div>
            <div class="kv"><div class="k">Current level</div><div class="v">${s.current_level != null ? s.current_level.toFixed(2) + ' m' : '–'}</div></div>
        </div>
        <h3>Level history <small style="color:#6a7194;font-weight:400">annual means, m above Adriatic</small></h3>
        <div class="chart-box" id="st-chart-box"><div style="text-align:center;padding-top:80px;"><div class="loading-spinner" style="margin:0 auto;"></div></div></div>
        <div class="note">Points from the last 10 years (red) drive the trend used in the GWI. Source: eHYD (BML).</div>
        ${hydroImpactHTML(hydroLinksForStation(s.id), false)}
        <div class="apirow">API: <code><a href="/llm/point/gw:${esc(s.id)}" target="_blank">/llm/point/gw:${esc(s.id)}</a></code></div>`;
    openModal('st-modal');
    currentShare = { st: s.id };
    updateURL();
    loadGWChart(s.id);
}
async function loadGWChart(stationId) {
    const box = $('st-chart-box');
    try {
        if (!gwTrendsCache) gwTrendsCache = await fetch('data/gw_stations_trends.json').then(r => r.json());
        const st = gwTrendsCache.find(x => String(x.id) === String(stationId));
        if (!st || !st.annual_data) { box.innerHTML = '<div style="text-align:center;padding-top:90px;color:#6a7194;">No historical data</div>'; return; }
        box.innerHTML = '<canvas></canvas>';
        const ctx = box.querySelector('canvas');
        const years = Object.keys(st.annual_data).sort();
        const values = years.map(y => st.annual_data[y]);
        const maxYear = Math.max(...years.map(Number));
        const ptCol = years.map(y => Number(y) >= maxYear - 10 ? 'rgb(255,99,132)' : 'rgb(79,195,247)');
        destroyChart();
        chart = new Chart(ctx, {
            type: 'line',
            data: { labels: years, datasets: [{
                data: values, borderColor: 'rgba(79,195,247,0.8)', borderWidth: 1.5,
                pointRadius: 2.5, pointBackgroundColor: ptCol, fill: false, tension: 0.15,
            }]},
            options: chartOpts('m'),
        });
    } catch (e) {
        box.innerHTML = '<div style="text-align:center;padding-top:90px;color:#6a7194;">Chart failed to load</div>';
    }
}

function openNO3Station(s) {
    destroyChart();
    const overLimit = s.latest != null && s.latest >= 50;
    const trend = s.trend_per_yr;
    const body = $('st-modal-body');
    body.innerHTML = `
        <h2>Nitrate station ${esc(s.id)}</h2>
        <div class="subtitle">EEA WISE-6 groundwater quality · ${s.first_year}–${s.last_year} · ${s.n_samples} samples</div>
        <div class="kv-grid">
            <div class="kv"><div class="k">Latest NO₃ (${s.latest_year})</div><div class="v" style="color:${no3Tint(s.latest)}">${s.latest != null ? s.latest.toFixed(1) + ' mg/L' : '–'}</div></div>
            <div class="kv"><div class="k">vs EU limit 50</div><div class="v">${s.latest != null ? Math.round(s.latest / 50 * 100) + '%' : '–'}${overLimit ? ' ⚠' : ''}</div></div>
            <div class="kv"><div class="k">Mean (all years)</div><div class="v">${s.mean != null ? s.mean.toFixed(1) + ' mg/L' : '–'}</div></div>
            <div class="kv"><div class="k">Trend</div><div class="v">${trend != null ? (trend > 0 ? '+' : '') + (trend * 10).toFixed(1) + ' mg/L/dec' : '–'}</div></div>
        </div>
        <h3>Nitrate history <small style="color:#6a7194;font-weight:400">annual means, mg/L</small></h3>
        <div class="chart-box" id="st-chart-box"></div>
        <div class="note">Red line: EU drinking-water limit (50 mg/L). Amber: Austrian quality target (45 mg/L). Values below LOQ counted as LOQ/2. Source: EEA Waterbase ICM.</div>
        <div class="apirow">API: <code><a href="/llm/point/no3:${esc(s.id)}" target="_blank">/llm/point/no3:${esc(s.id)}</a></code></div>`;
    openModal('st-modal');
    currentShare = { no3: s.id };
    updateURL();
    const box = $('st-chart-box');
    box.innerHTML = '<canvas></canvas>';
    const years = Object.keys(s.annual || {}).sort();
    const values = years.map(y => s.annual[y]);
    const opts = chartOpts('mg/L');
    opts.scales.y.suggestedMax = Math.max(55, ...values.map(v => v * 1.1));
    opts.scales.y.suggestedMin = 0;
    chart = new Chart(box.querySelector('canvas'), {
        type: 'line',
        data: { labels: years, datasets: [
            { data: values, borderColor: 'rgba(240,170,90,0.9)', borderWidth: 1.5,
              pointRadius: 3, pointBackgroundColor: values.map(no3Tint), fill: false, tension: 0.15 },
            { data: years.map(() => 50), borderColor: 'rgba(233,69,96,0.6)', borderWidth: 1, borderDash: [6, 4], pointRadius: 0 },
            { data: years.map(() => 45), borderColor: 'rgba(243,156,18,0.4)', borderWidth: 1, borderDash: [3, 4], pointRadius: 0 },
        ]},
        options: opts,
    });
}

function chartOpts(unit) {
    return {
        responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
        plugins: { legend: { display: false }, tooltip: {
            callbacks: { label: c => (c.parsed.y != null ? c.parsed.y.toFixed(2) + ' ' + unit : '') } } },
        scales: {
            x: { ticks: { color: '#6a7194', maxTicksLimit: 12, font: { size: 10 } }, grid: { color: 'rgba(58,63,85,0.3)' } },
            y: { ticks: { color: '#6a7194', font: { size: 10 } }, grid: { color: 'rgba(58,63,85,0.3)' } },
        },
    };
}

// ---------- search ----------
let searchTimer = null, searchSeq = 0, activeIdx = -1;
function wireUI() {
    const inp = $('search');
    inp.addEventListener('input', () => {
        clearTimeout(searchTimer);
        const q = inp.value.trim();
        if (q.length < 2) { hideResults(); return; }
        renderResults(localSearch(q), q, true);           // instant local
        searchTimer = setTimeout(() => remoteSearch(q), 350); // debounced remote
    });
    inp.addEventListener('keydown', e => {
        const items = document.querySelectorAll('.sr-item');
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            activeIdx = Math.max(0, Math.min(items.length - 1, activeIdx + (e.key === 'ArrowDown' ? 1 : -1)));
            items.forEach((el, i) => el.classList.toggle('active', i === activeIdx));
            if (items[activeIdx]) items[activeIdx].scrollIntoView({ block: 'nearest' });
        } else if (e.key === 'Enter') {
            const el = items[activeIdx >= 0 ? activeIdx : 0];
            if (el) el.click();
        } else if (e.key === 'Escape') hideResults();
    });
    document.addEventListener('click', e => { if (!$('searchwrap').contains(e.target)) hideResults(); });

    $('share-btn').addEventListener('click', () => copyShare($('share-btn')));
    $('methods-link').addEventListener('click', e => { e.preventDefault(); showMethods(); });
    map.on('moveend', updateURL);
}
function hideResults() { $('search-results').style.display = 'none'; activeIdx = -1; }
function norm(s) { return s.toLowerCase().replace(/ä/g, 'a').replace(/ö/g, 'o').replace(/ü/g, 'u').replace(/ß/g, 'ss'); }
function localSearch(q) {
    const nq = norm(q), out = [];
    for (const name in muniByName) {
        if (out.length >= 6) break;
        if (norm(name).includes(nq)) {
            const m = muniByName[name];
            out.push({ type: 'Gemeinde', label: m.name, sub: 'GWI ' + (m.gwi != null ? m.gwi.toFixed(2) : '–'),
                lat: m.lat, lon: m.lon, zoom: 12, gem: String(m.iso) });
        }
    }
    let kgHits = 0;
    for (const [code, r] of kgRegList) {
        if (kgHits >= 6) break;
        if (norm(r.n).includes(nq)) {
            const rec = gwiKG[code];
            out.push({ type: 'KG', label: r.n, sub: code + (rec && rec.i != null ? ' · GWI ' + rec.i.toFixed(2) : ''),
                lat: r.lat, lon: r.lon, zoom: 13, kg: code });
            kgHits++;
        }
    }
    return out;
}
async function remoteSearch(q) {
    const seq = ++searchSeq;
    $('search-spinner').style.display = 'block';
    const local = localSearch(q);
    const remote = [];
    try {
        const looksAddress = /\d/.test(q) || q.split(/\s+/).length >= 2;
        const [lk, addr] = await Promise.all([
            fetch(CADASTRE + '/api/v1/lookup?limit=6&q=' + encodeURIComponent(q)).then(r => r.json()).catch(() => ({ data: [] })),
            looksAddress
                ? fetch(CADASTRE + '/api/v1/search/address_osm?limit=4&q=' + encodeURIComponent(q)).then(r => r.json()).catch(() => ({ data: [] }))
                : Promise.resolve({ data: [] }),
        ]);
        for (const d of (lk.data || [])) {
            const t = d.type === 'plz' ? 'PLZ' : d.type === 'kg' ? 'KG' : d.type === 'ortschaft' ? 'Ortschaft' : 'Gemeinde';
            const kg = d.kg_code || null;
            const gem = d.gemeinde_code || null;
            let lat = null, lon = null;
            if (kg && kgReg[kg]) { lat = kgReg[kg].lat; lon = kgReg[kg].lon; }
            else if (gem && muniByIso[gem]) { lat = muniByIso[gem].lat; lon = muniByIso[gem].lon; }
            if (lat == null) continue;
            remote.push({ type: t, label: d.name || d.code, sub: (d.gemeinde_name && d.gemeinde_name !== d.name ? d.gemeinde_name : '') || d.code || '',
                lat, lon, zoom: kg ? 13 : 12, kg, gem: kg ? null : gem });
        }
        for (const d of (addr.data || [])) {
            remote.push({ type: 'Address', label: d.display_name.split(',').slice(0, 3).join(','), sub: d.nearest_kg ? d.nearest_kg.kg_name : '',
                lat: d.lat, lon: d.lon, zoom: 15, latlonKG: true });
        }
    } catch (e) { /* keep local results */ }
    $('search-spinner').style.display = 'none';
    if (seq !== searchSeq) return; // stale
    // merge, dedupe by label+type
    const seen = new Set(), merged = [];
    for (const r of [...local, ...remote]) {
        const k = r.type + '|' + r.label + '|' + (r.sub || '');
        if (!seen.has(k)) { seen.add(k); merged.push(r); }
    }
    renderResults(merged.slice(0, 12), q, false);
}
function renderResults(results, q, isLocalOnly) {
    const box = $('search-results');
    if (!results.length) {
        box.innerHTML = isLocalOnly ? '' : '<div class="sr-item" style="cursor:default;color:#6a7194;">No results</div>';
        box.style.display = isLocalOnly ? 'none' : 'block';
        return;
    }
    activeIdx = -1;
    box.innerHTML = results.map((r, i) =>
        `<div class="sr-item" data-i="${i}">
            <span class="sr-type">${r.type}</span>
            <span>${esc(r.label)}</span>
            <span class="sr-sub">${esc(r.sub || '')}</span>
        </div>`).join('');
    box.style.display = 'block';
    box.querySelectorAll('.sr-item').forEach((el, i) => el.addEventListener('click', () => pickResult(results[i])));
}
async function pickResult(r) {
    hideResults();
    $('search').blur();
    map.flyTo([r.lat, r.lon], r.zoom || 12, { duration: 0.9 });
    if (r.kg) setTimeout(() => showKGModal(r.kg, { noFly: true }), 500);
    else if (r.latlonKG) setTimeout(() => openKGAt(r.lat, r.lon), 500);
    else if (r.gem) setTimeout(() => openKGAt(r.lat, r.lon), 500);
}

// ---------- share URLs ----------
function updateURL() {
    if (!map) return;
    const c = map.getCenter();
    const p = new URLSearchParams();
    p.set('v', c.lat.toFixed(4) + ',' + c.lng.toFixed(4) + ',' + map.getZoom());
    for (const k of ['kg', 'st', 'no3', 'gem']) if (currentShare[k]) p.set(k, currentShare[k]);
    history.replaceState(null, '', '?' + p.toString());
}
function copyShare(btn) {
    updateURL();
    navigator.clipboard.writeText(location.href).then(() => toast('Link copied to clipboard'))
        .catch(() => toast(location.href));
}
function toast(msg) {
    const t = $('toast');
    t.textContent = msg; t.style.display = 'block';
    clearTimeout(t._h); t._h = setTimeout(() => t.style.display = 'none', 2200);
}
function restoreFromURL() {
    const p = new URLSearchParams(location.search);
    const v = p.get('v');
    if (v) {
        const [lat, lng, z] = v.split(',').map(Number);
        if (isFinite(lat) && isFinite(lng)) map.setView([lat, lng], isFinite(z) ? z : 9, { animate: false });
    }
    if (p.get('kg') && kgReg[p.get('kg')]) showKGModal(p.get('kg'), { noFly: !v });
    else if (p.get('st')) openGWStationById(p.get('st'));
    else if (p.get('no3')) openNO3StationById(p.get('no3'));
    else if (p.get('gem') && muniByIso[p.get('gem')]) {
        const m = muniByIso[p.get('gem')];
        if (!v) map.setView([m.lat, m.lon], 12, { animate: false });
        openKGAt(m.lat, m.lon);
    }
    if (p.get('methods') === '1') showMethods();
}

// ---------- methods modal ----------
function showMethods() {
    $('methods-body').innerHTML = `
    <h2>Methods &amp; sources</h2>
    <div class="subtitle">Everything on this map, honestly documented. Generated ${esc(gwiMeta.generated)}.</div>

    <h3>The Groundwater Status Index (GWI)</h3>
    <p>One number per Katastralgemeinde (KG), 0 = good → 1 = stressed, evaluated at each of Austria's
    7,850 KG centroids and averaged per Gemeinde for the map colouring. It is a <b>weighted mean of five
    sub-risks</b>, each clamped to 0–1:</p>
    <ul>
        <li><b>Level trend — 35%.</b> Inverse-distance-weighted (IDW) mean of the 10-year groundwater level
            trend of eHYD stations within 12.5&nbsp;km (fallback: nearest 3 within 30&nbsp;km, flagged
            <i>estimated</i>). Risk = clamp(−trend / 0.5&nbsp;m per decade): a sustained decline of 0.5&nbsp;m/decade
            scores maximum risk; rising levels score 0.</li>
        <li><b>Precipitation divergence — 15%.</b> How far the 5-year groundwater level sits below what local
            precipitation history would explain (regression of levels on NASA POWER precipitation; residual in
            σ units). Persistent negative divergence suggests abstraction or structural loss rather than weather.
            Risk = clamp(−divergence / 1.5σ).</li>
        <li><b>Nitrate — 25%.</b> IDW mean of the latest annual-mean NO₃ concentration of EEA WISE-6 stations
            (only stations still reporting since ≥ 2015), same radii. Risk = clamp(latest / 50&nbsp;mg/L, the EU
            drinking-water limit).</li>
        <li><b>WFD status — 10%.</b> WISE Water Framework Directive 2022 chemical + ecological status of water
            bodies attributed to the Gemeinde (0–1). Only counted where GW bodies are actually monitored.</li>
        <li><b>Drought pressure — 15%.</b> Copernicus EDO Combined Drought Indicator mean class of the Gemeinde,
            2012–2023. Risk = clamp(mean CDI / 2).</li>
    </ul>
    <p>Weights are <b>renormalized over available components</b>: where e.g. no nitrate station is in reach,
    the remaining components carry the weight — the index never silently treats missing data as zero risk.
    Categories: <span class="badge good">good</span> &lt; 0.30 ≤ <span class="badge watch">watch</span>
    &lt; 0.50 ≤ <span class="badge stressed">stressed</span>. The trend scale was calibrated so the national
    distribution lands at roughly 28% good / 40% watch / 31% stressed — the categories are relative national
    context, not regulatory judgements.</p>

    <h3>Hydropower influence (informational, not in the GWI)</h3>
    <p>Where a KG or station modal shows a <b>Hydropower influence</b> section, we detected a statistically
    significant coupling between an upstream hydro plant's daily water releases and the day-to-day movements
    of a downstream groundwater well. How it works:</p>
    <ul>
        <li><b>Releases.</b> ENTSO-E per-generation-unit output (A73, 15-min → daily MWh) for 22 major Austrian
            hydro plants. Units still publishing in 2026 are used directly; for plants whose per-unit feed stopped
            (mostly the Danube run-of-river cascade), the national per-type series is <b>downscaled</b> with a
            per-plant linear fit calibrated on that plant's own 2023–24 unit data (calibration r ≈ 0.6–0.8).</li>
        <li><b>River topology.</b> Each plant's tailrace is snapped to the OSM waterway network and the river is
            walked <i>downstream</i> (flow direction, up to 120 km). Live eHYD groundwater wells within 4 km of the
            downstream channel and river gauges within 800 m form the candidate set.</li>
        <li><b>Test.</b> Per (plant, well) pair, daily first differences of the well level are regressed on local
            precipitation (NASA POWER, lags 0–3 + 7-day sum) with and without the plant's release changes
            (t, t−1). We report the partial R² of the release terms, an F-test p-value, and a placebo check
            (release series shifted 60 days). Shown only if p&lt;0.01, partial R² ≥ 5%, and above placebo.</li>
        <li><b>Limits.</b> This is correlation with controls, not proven causation — upstream releases and
            downstream groundwater both respond to basin hydrology, and the precipitation control is coarse
            (0.5° grid). Downscaled plants share the national daily signal shape, so attribution among plants on the
            <i>same</i> river rests on topology, not unique signals. That is why this evidence is displayed but
            <b>not folded into the index</b>. River gauges confirm the pathway: on the Ziller, releases explain
            25–80% of daily stage changes at downstream gauges.</li>
    </ul>

    <h3>Data sources</h3>
    <ul>
        <li><b>eHYD (BML)</b> — 3,732 groundwater level stations, annual means, most 1966–2022. Trends are
            Theil–Sen/OLS on annual means; the 10-year window drives the model.</li>
        <li><b>EEA Waterbase ICM 2026 (WISE-6 SoE)</b> — 2,250 Austrian groundwater quality stations, nitrate
            1992–2024, annual means per station.</li>
        <li><b>WISE WFD 2022</b> — water-body chemical/ecological status and at-risk flags.</li>
        <li><b>Copernicus European Drought Observatory</b> — Combined Drought Indicator, 10-day grids
            2012–2023, zonally aggregated per Gemeinde.</li>
        <li><b>NASA POWER</b> — daily precipitation (0.5° grid) behind the divergence component.</li>
        <li><b>ENTSO-E Transparency</b> (via austria-power.exe.xyz) — per-unit hydro generation (A73) and
            national per-type generation, 15-min since 2023, behind the hydropower influence section.</li>
        <li><b>OSM/Geofabrik waterways</b> — 338k river/stream segments; directed flow network for the
            downstream plant→station matching.</li>
        <li><b>BEV cadastre / Statistik Austria</b> (via the Kohlschwarz cadastre API) — canonical KG &amp;
            Gemeinde registry, geometry lookups, address search. Every station is snapped once to its KG by
            exact point-in-polygon.</li>
    </ul>

    <h3>Honest limitations</h3>
    <ul>
        <li><b>Interpolation is not measurement.</b> Between stations the index is an IDW estimate; the
            ◌&nbsp;<i>estimated</i> flag marks KGs where even the 12.5&nbsp;km radius was empty and the nearest-3
            (≤ 30 km) fallback was used. Alpine areas are sparsely monitored.</li>
        <li><b>Groundwater doesn't follow administrative borders.</b> Aquifers ignore KG lines; treat sharp
            colour steps between neighbours with skepticism.</li>
        <li><b>WFD status is per water body, not per station</b>, and its Gemeinde attribution is approximate.</li>
        <li><b>Nitrate values below the limit of quantification are counted as LOQ/2</b> (standard convention) —
            very clean stations may be slightly overstated.</li>
        <li><b>Precipitation grid is coarse</b> (~50 km); the divergence component blurs local rainfall
            differences, especially in mountain valleys.</li>
        <li><b>Trend windows differ per station</b> (records end 2020–2022 for most eHYD stations; nitrate runs
            to 2024). "Latest" is the newest year each source provides.</li>
        <li>The Gemeinde colour is the <b>mean over its KGs</b> — tap the map for KG-level values.</li>
    </ul>

    <h3>Reproducibility &amp; API</h3>
    <p>The full pipeline is open: <code>scripts/build_gw_index.py</code> in the repo computes the index;
    every per-KG value is served machine-readably at <code>/llm/kg/{kg_code}</code>
    (<a href="/llm/manifest.json" target="_blank">manifest</a>), following the Kohlschwarz sibling-service
    integration spec. The old multi-layer explorer with all raw layers lives on at
    <a href="explore.html">explore.html</a>. Data license CC-BY-4.0; underlying sources retain their own terms.</p>`;
    openModal('methods-modal');
}

// ---------- start ----------
boot().catch(e => {
    $('loading-overlay').innerHTML = '<div class="t">Failed to load</div><div class="s">' + esc(e.message) + '</div>';
    console.error(e);
});
