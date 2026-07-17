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
// WFD / GWD thresholds for nitrate (mg/L NO3)
const NO3_LIMIT = 50;          // EU groundwater quality standard (GWD 2006/118/EC Annex I)
const NO3_TREND_REVERSAL = 37.5; // 75% of standard: trend-reversal trigger (GWD Art. 5(2))
const NO3_AT_TARGET = 45;      // Austrian QZV Chemie GW quality target
const COMPONENTS = [ // [key in gwi record, label, weight, raw key, raw formatter]
    ['q_trend',   'Level trend',        0.30, 'gw_trend', v => fmtTrend(v)],
    ['q_div',     'Precip divergence',  0.10, 'gw_div',   v => v.toFixed(2) + ' σ'],
    ['q_use',     'Abstraction vs resource', 0.15, 'use_pct', v => v.toFixed(0) + '% of GWK'],
    ['q_nitrate', 'Nitrate',            0.20, 'no3',      v => v.toFixed(1) + ' mg/L'],
    ['q_wfd',     'WFD status risk',    0.10, null,       null],
    ['q_edo',     'Drought pressure',   0.15, null,       null],
];

// ---------- state ----------
let map, choroLayer, gwLayerGroup, no3LayerGroup;
let no3BodyLayer = null;        // GWK polygons tinted by aquifer nitrate (heat layer)
let no3BodyOn = false;          // nitrate aquifer fill active -> dim choropleth
// legend filters: which classes are visible
const filt = {
    cat: { good: true, watch: true, stressed: true },   // choropleth GWI categories
    trend: { falling: true, stable: true, rising: true }, // level-station classes
    no3: [true, true, true, true],                        // nitrate bands (see NO3_BANDS)
    use: { low: true, mid: true, high: true },            // water-use intensity classes
};
let gwiKG = null;          // gw_index_kg.json .kgs
let gwiMeta = null;
let kgReg = null;          // kg_registry.json
let gwStations = [];       // slim
let plantInfl = null;      // plant_influence.json (hydropower downstream impact)
let no3Stations = [];      // nitrate stations
let muniByIso = {}, muniByName = {};
let gwTrendsCache = null;  // lazy full annual data
let plantProfiles = null;  // lazy plant_profiles.json (per-plant generation + downstream)
let gaugesSlim = null;     // eager gauges_slim.json (river gauge index for proximity lists)
let gaugeProfiles = null;  // lazy gauge_profiles.json (per-gauge annual + live flow)
let hpStack = [];          // modal back-stack for plant/gauge modals: [{kind:'kg'|'gw'|'no3'|'hp'|'pg', id}]
let popData = null;        // population.json (Statistik Austria)
let gwkCtx = null;         // gwk_context.json (Wasserschatz per GW body)
let gwkLayer = null;       // GW-body boundary overlay (lazy)
let chart = null;          // active Chart.js instance
let popChart = null;       // population trend chart in KG modal
let currentShare = {};     // extra params beyond view
let stNav = null;          // station-browsing context: {back:{kind,id,label}, items:[{k,id,name}], idx}
let lastKGCtx = null;      // last opened KG: {code, name, lat, lon}
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

// Trend formatter: "cm/decade" spelled out (expert feedback: "/dec" was unclear).
// Input is m/decade.
function fmtTrend(v, digits = 0) {
    if (v == null) return '–';
    return (v > 0 ? '+' : '') + (v * 100).toFixed(digits) + ' cm/decade';
}
const TREND_TITLE = 'Change of the groundwater level per 10 years (linear trend over the last decade of annual means). Negative = falling level.';
const NO3_TITLE = 'Nitrate concentration. EU/WFD groundwater quality standard: 50 mg/L; trend reversal required from 37.5 mg/L (75% of the standard) if rising; Austrian target: 45 mg/L.';

// ---------- boot ----------
async function boot() {
    map = L.map('map', {
        zoomControl: true, preferCanvas: true,
        center: [47.6, 13.5], zoom: 7, minZoom: 6, maxZoom: 18,
        zoomSnap: 0.5, attributionControl: true,
    });
    map.zoomControl.setPosition('bottomleft');
    // Dedicated panes so station dots always render above choropleth + GWK polygons.
    map.createPane('gwkfill');  map.getPane('gwkfill').style.zIndex = 410;
    map.createPane('stations'); map.getPane('stations').style.zIndex = 620;
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
    popData = await fetch('data/population.json').then(r => r.json()).catch(() => null);
    gaugesSlim = await fetch('data/gauges_slim.json').then(r => r.json()).catch(() => null);
    gwkCtx = await fetch('data/gwk_context.json').then(r => r.json()).catch(() => null);
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
function gwiCat(g) {
    if (g == null) return null;
    return g < 0.30 ? 'good' : g < 0.50 ? 'watch' : 'stressed';
}
function choroStyle(f) {
    const g = f.properties.gwi;
    const cat = gwiCat(g);
    const shown = cat == null || filt.cat[cat];
    // dim the whole choropleth when the nitrate aquifer layer is on, so it reads clearly
    const base = no3BodyOn ? 0.12 : 0.55;
    return {
        fillColor: gwiColor(g),
        fillOpacity: shown ? base : 0.03,
        color: '#0d1022', weight: 0.5, opacity: shown ? (no3BodyOn ? 0.2 : 0.6) : 0.1,
    };
}
function refreshChoropleth() { if (choroLayer) choroLayer.setStyle(choroStyle); }
function buildChoropleth(geo) {
    choroLayer = L.geoJSON(geo, {
        style: choroStyle,
        onEachFeature: (f, layer) => {
            const p = f.properties;
            const g = p.gwi != null ? p.gwi.toFixed(2) : '–';
            const cat = p.gwi_category || 'no data';
            layer.bindTooltip(() => {
                let pop = '';
                const r = popForIso(p.iso);
                if (r) {
                    const now = r.t[r.t.length - 1], first = r.t[0];
                    const d = (now - first) / first * 100;
                    pop = `<br>${now.toLocaleString('en')} people · ${d >= 0 ? '+' : ''}${d.toFixed(0)}% since 2002`;
                }
                return `<b>${esc(p.name)}</b><br>GWI ${g} · <span style="color:${CAT_COLOR[cat] || '#8b93b8'}">${cat}</span>${pop}`;
            }, { className: 'gw-tip', sticky: true });
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
// Continuous nitrate colour scale anchored on the WFD/GWD thresholds so that
// e.g. 14 and 100 mg/L never share a colour. Stops: [mg/L, rgb].
const NO3_GRAD = [
    [0,    [0x5f, 0x8a, 0xc7]],  // clean – blue
    [25,   [0x8f, 0xb0, 0x8a]],  // half the trend-reversal trigger – blue-green
    [37.5, [0xd8, 0xb4, 0x55]],  // GWD trend-reversal threshold (75%) – amber
    [45,   [0xe8, 0x8a, 0x48]],  // Austrian target – orange
    [50,   [0xe0, 0x52, 0x52]],  // EU quality standard – red
    [100,  [0x8f, 0x1d, 0x2f]],  // gross exceedance – dark red
];
function no3Tint(v) {
    if (v == null || isNaN(v)) return '#6a6a8a';
    v = Math.max(0, Math.min(100, v));
    for (let i = 1; i < NO3_GRAD.length; i++) {
        if (v <= NO3_GRAD[i][0]) {
            const [p0, c0] = NO3_GRAD[i - 1], [p1, c1] = NO3_GRAD[i];
            const t = (v - p0) / (p1 - p0);
            const c = c0.map((a, j) => Math.round(a + t * (c1[j] - a)));
            return `rgb(${c[0]},${c[1]},${c[2]})`;
        }
    }
    return '#8f1d2f';
}
function dotStyle() {
    const z = map.getZoom();
    return {
        radius: z <= 7 ? 2.2 : z <= 9 ? 3 : z <= 11 ? 4 : 5.5,
        fillOpacity: z <= 7 ? 0.85 : 0.92,
        weight: z <= 8 ? 0.6 : 1,
    };
}
// classify stations for legend filtering
function trendClass(t) { return t == null ? 'stable' : t < -0.1 ? 'falling' : t > 0.1 ? 'rising' : 'stable'; }
// nitrate legend bands: [label, test]
const NO3_BANDS = [
    [v => v < 25, '< 25'],
    [v => v >= 25 && v < 37.5, '25–37.5'],
    [v => v >= 37.5 && v < 50, '37.5–50'],
    [v => v >= 50, '≥ 50'],
];
function no3Band(v) {
    if (v == null || isNaN(v)) return 0;
    for (let i = 0; i < NO3_BANDS.length; i++) if (NO3_BANDS[i][0](v)) return i;
    return NO3_BANDS.length - 1;
}
function applyStationFilters() {
    const d = dotStyle();
    gwLayerGroup.eachLayer(m => {
        const on = filt.trend[m._cls];
        m.setStyle({ radius: on ? d.radius : 0.1, fillOpacity: on ? d.fillOpacity : 0, opacity: on ? 1 : 0, weight: on ? d.weight : 0 });
    });
    no3LayerGroup.eachLayer(m => {
        const on = filt.no3[m._cls];
        m.setStyle({ radius: on ? d.radius : 0.1, fillOpacity: on ? d.fillOpacity : 0, opacity: on ? 1 : 0, weight: on ? d.weight : 0 });
    });
}
function buildStationLayers() {
    const rnd = L.canvas({ padding: 0.4, pane: 'stations' });
    const ds = dotStyle();
    gwLayerGroup = L.layerGroup();
    for (const s of gwStations) {
        const m = L.circleMarker([s.lat, s.lon], {
            renderer: rnd, pane: 'stations', radius: ds.radius, weight: ds.weight,
            color: 'rgba(8,10,24,0.9)',
            fillColor: trendTint(s.trend_m_per_decade), fillOpacity: ds.fillOpacity,
        });
        m._cls = trendClass(s.trend_m_per_decade);
        m.on('click', e => { L.DomEvent.stop(e); stNav = null; openGWStation(s); });
        m.bindTooltip(() => `<b>${esc(s.name)}</b><br>level trend ${fmtTrend(s.trend_m_per_decade)}`,
            { className: 'gw-tip' });
        gwLayerGroup.addLayer(m);
    }
    no3LayerGroup = L.layerGroup();
    for (const s of no3Stations) {
        const m = L.circleMarker([s.lat, s.lon], {
            renderer: rnd, pane: 'stations', radius: ds.radius, weight: ds.weight,
            color: 'rgba(8,10,24,0.9)',
            fillColor: no3Tint(s.latest), fillOpacity: ds.fillOpacity,
        });
        m._cls = no3Band(s.latest);
        m.on('click', e => { L.DomEvent.stop(e); stNav = null; openNO3Station(s); });
        m.bindTooltip(() => `<b>${esc(s.id)}</b><br>${s.latest != null ? s.latest.toFixed(1) + ' mg/L NO₃ (' + s.latest_year + ') · ' + Math.round(s.latest / NO3_LIMIT * 100) + '% of 50 mg/L' : '–'}`,
            { className: 'gw-tip' });
        no3LayerGroup.addLayer(m);
    }
    map.on('zoomend', applyStationFilters);
    gwLayerGroup.addTo(map);
    $('n-gw').textContent = `(${gwStations.length})`;
    $('n-no3').textContent = `(${no3Stations.length})`;
    $('tg-gw').addEventListener('change', e => {
        e.target.checked ? gwLayerGroup.addTo(map) : map.removeLayer(gwLayerGroup);
        $('leg-gw').style.display = e.target.checked ? '' : 'none';
        updateURL();
    });
    $('tg-no3').addEventListener('change', async e => {
        $('leg-no3').style.display = e.target.checked ? '' : 'none';
        if (e.target.checked) {
            hintChips($('leg-no3'));
            no3LayerGroup.addTo(map);
            await ensureNO3BodyLayer();
            no3BodyLayer.addTo(map);
            no3BodyOn = true;
        } else {
            map.removeLayer(no3LayerGroup);
            if (no3BodyLayer) map.removeLayer(no3BodyLayer);
            no3BodyOn = false;
        }
        refreshChoropleth();
        applyStationFilters();
        updateURL();
    });
    $('tg-gwk').addEventListener('change', async e => {
        $('leg-gwk').style.display = e.target.checked ? '' : 'none';
        if (!e.target.checked) { if (gwkLayer) map.removeLayer(gwkLayer); return; }
        if (!gwkLayer) {
            const gj = await fetchGwkGeo();
            gwkLayer = L.geoJSON(gj, {
                pane: 'gwkfill',
                style: gwkStyle,
                onEachFeature: (f, ly) => {
                    ly.bindTooltip(`<b>${esc(f.properties.n)}</b><br>${f.properties.u}% of resource abstracted`, { sticky: true });
                    // pass taps through to the KG choropleth underneath
                    ly.on('click', e => openKGAt(e.latlng.lat, e.latlng.lng));
                },
            });
        }
        gwkLayer.addTo(map);
        hintChips($('leg-gwk'));
    });
    // append updateURL to gwk toggle too
    $('tg-gwk').addEventListener('change', updateURL);
}

// ---------- nitrate aquifer heat layer ----------
let gwkGeoCache = null;
async function fetchGwkGeo() {
    if (!gwkGeoCache) gwkGeoCache = await fetch('data/gwk.geojson').then(r => r.json());
    return gwkGeoCache;
}
// median of latest NO3 per groundwater body, recent stations only
function no3ByBody() {
    const acc = {};
    for (const s of no3Stations) {
        if (!s.body || s.latest == null || s.latest_year < 2015) continue;
        (acc[s.body] = acc[s.body] || []).push(s.latest);
    }
    const out = {};
    for (const b in acc) {
        const v = acc[b].sort((a, x) => a - x);
        out[b] = { med: v[Math.floor(v.length / 2)], n: v.length };
    }
    return out;
}
async function ensureNO3BodyLayer() {
    if (no3BodyLayer) return no3BodyLayer;
    const gj = await fetchGwkGeo();
    const agg = no3ByBody();
    no3BodyLayer = L.geoJSON(gj, {
        pane: 'gwkfill',
        style: f => {
            const a = agg[f.properties.id];
            return a
                ? { fillColor: no3Tint(a.med), fillOpacity: 0.42, color: '#0d1022', weight: 0.8, opacity: 0.5 }
                : { fillOpacity: 0, opacity: 0, weight: 0 };
        },
        onEachFeature: (f, ly) => {
            const a = agg[f.properties.id];
            ly.bindTooltip(`<b>${esc(f.properties.n)}</b><br>${a
                ? `median ${a.med.toFixed(1)} mg/L NO₃ · ${Math.round(a.med / NO3_LIMIT * 100)}% of 50 mg/L · ${a.n} stations`
                : 'no recent nitrate data'}`, { className: 'gw-tip', sticky: true });
            ly.on('click', e => openKGAt(e.latlng.lat, e.latlng.lng));
        },
    });
    return no3BodyLayer;
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
function nearStations(lat, lon, radiusKm) {
    const near = t => t
        .map(s => ({ s, d: distKm(lat, lon, s.lat, s.lon) }))
        .filter(x => x.d <= radiusKm)
        .sort((a, b) => a.d - b.d).slice(0, 8);
    return { gws: near(gwStations), n3s: near(no3Stations) };
}
function stationListHTML(lat, lon, radiusKm) {
    const { gws, n3s } = nearStations(lat, lon, radiusKm);
    let html = '';
    if (gws.length) {
        html += `<h3>Groundwater level stations <small style="color:#6a7194;font-weight:400">≤ ${radiusKm} km</small></h3><div class="station-list">` +
            gws.map(({ s, d }) => {
                const t = s.trend_m_per_decade;
                return `<div class="station-item" onclick="stNavOpen('gw','${esc(s.id)}')">
                    <span class="dot" style="background:${trendTint(t)}"></span>
                    <span class="nm">${esc(s.name)}</span>
                    <span class="meta">${d.toFixed(1)} km</span>
                    <span class="val" title="${TREND_TITLE}" style="color:${t != null && t < -0.1 ? '#f28a7d' : t != null && t > 0.1 ? '#7ec8e0' : '#b9c0dd'}">${fmtTrend(t)}</span>
                </div>`;
            }).join('') + '</div>';
    }
    if (n3s.length) {
        html += `<h3>Nitrate stations <small style="color:#6a7194;font-weight:400">≤ ${radiusKm} km</small></h3><div class="station-list">` +
            n3s.map(({ s, d }) => `<div class="station-item" onclick="stNavOpen('no3','${esc(s.id)}')">
                    <span class="dot" style="background:${no3Tint(s.latest)}"></span>
                    <span class="nm">${esc(s.id)}</span>
                    <span class="meta">${d.toFixed(1)} km · ${s.latest_year || ''}</span>
                    <span class="val" style="color:${no3Tint(s.latest)}">${s.latest != null ? s.latest.toFixed(1) + ' mg/L' : '–'}</span>
                </div>`).join('') + '</div>';
    }
    const pgs = !gaugesSlim ? [] : gaugesSlim
        .map(s => ({ s, d: distKm(lat, lon, s.lat, s.lon) }))
        .filter(x => x.d <= radiusKm)
        .sort((a, b) => a.d - b.d).slice(0, 6);
    if (pgs.length) {
        html += `<h3>River gauges <small style="color:#6a7194;font-weight:400">≤ ${radiusKm} km</small></h3><div class="station-list">` +
            pgs.map(({ s, d }) => {
                const tr = s.t;
                const trCol = tr == null ? '#8b93b8' : tr < -5 ? '#f28a7d' : tr > 5 ? '#7ed37e' : '#8b93b8';
                return `<div class="station-item" onclick="pgOpen('${esc(s.id)}')">
                    <span class="dot" style="background:${s.live ? '#8fd08a' : '#8b93b8'}"></span>
                    <span class="nm">${esc(s.n)} <small style="color:#6a7194">${esc(s.riv)}</small></span>
                    <span class="meta">${d.toFixed(1)} km${s.q != null ? ' · ' + s.q + ' m³/s' : ''}</span>
                    <span class="val" style="color:${trCol}">${tr != null ? (tr > 0 ? '+' : '') + tr + '%/dec' : (s.live ? 'live' : '–')}</span>
                </div>`;
            }).join('') + '</div>';
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
    const W = 260, H = 48, n = sp.lvl.length;
    const pts = a => a.map((v, i) =>
        `${(i / (n - 1) * W).toFixed(1)},${(H - 4 - v / 100 * (H - 10)).toFixed(1)}`).join(' ');
    const d0 = sp.d0.slice(5).replace('-', '/'), d1 = sp.d1.slice(5).replace('-', '/');
    const range = (sp.lvl_max - sp.lvl_min);
    return `<div class="hydro-spark" style="margin:2px 0 6px 20px;cursor:pointer;" onclick="hpOpen('${esc(l.plant)}')" title="Tap for plant details: generation history, reservoir storage, downstream gauges">
        <svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="display:block;background:#141a2e;border-radius:6px;">
            <line x1="0" y1="${H / 2}" x2="${W}" y2="${H / 2}" stroke="#26315e" stroke-width="0.6"/>
            <polyline points="${pts(sp.rel)}" fill="none" stroke="#8fb8f2" stroke-width="1.1" opacity="0.7" stroke-linejoin="round"/>
            <polyline points="${pts(sp.lvl)}" fill="none" stroke="#facc6b" stroke-width="1.6" stroke-linejoin="round"/>
        </svg>
        <small style="color:#6a7194;"><span style="color:#facc6b">━</span> well level ${sp.lvl_min}–${sp.lvl_max} m <span title="Both curves are independently scaled to their own min–max over the window shown, to make co-movement visible — vertical positions are not comparable between the two curves." style="cursor:help;border-bottom:1px dotted #4a5578">(span ${range < 0.995 ? (range * 100).toFixed(0) + ' cm' : range.toFixed(2) + ' m'})</span>
        &nbsp;<span style="color:#8fb8f2">━</span> daily release &nbsp;·&nbsp; ${d0}–${d1} · each scaled to own range${liveTag(sp.d1, 8)}</small>
    </div>`;
}
function hydroLinkRowHTML(l, showStation) {
    const p = plantInfl.plants[l.plant] || {};
    const dir = l.beta_sum > 0 ? '↑ level rises with releases' : '↓ level falls with releases';
    const share = Math.round(l.partial * 100);
    return `<div class="station-item" style="cursor:default;display:block;">
        <div style="display:flex;align-items:center;gap:8px;">
        <span class="dot" style="background:#8fb8f2"></span>
        <span class="nm"><a href="#" onclick="hpOpen('${esc(l.plant)}');return false;" title="Open plant details: generation history, reservoir storage, downstream gauges">${esc(p.name || l.plant)}</a> <small style="color:#6a7194">${esc(p.type || '')} · ${p.mw || '?'} MW · ${esc(p.river || '')}</small>${showStation ? `<br><small style="color:#6a7194">at ${esc(l.name)} (<a href="#" onclick="stNavOpen('gw','${esc(l.station)}');return false;">${esc(l.station)}</a>)</small>` : ''}</span>
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

// ---------- live-data tag ----------
function liveTag(lastDate, maxAgeDays) {
    if (!lastDate) return '';
    const age = (Date.now() - new Date(lastDate + 'T00:00:00Z').getTime()) / 86400e3;
    if (age > (maxAgeDays || 8)) return '';
    return ` <span class="live-tag" title="Refreshed daily from live feeds · latest data point ${esc(lastDate)}">LIVE</span>`;
}
function lastDateOf(d0, vals) { // last non-null index -> ISO date
    let i = vals.length - 1;
    while (i >= 0 && vals[i] == null) i--;
    if (i < 0) return null;
    return new Date(new Date(d0 + 'T00:00:00Z').getTime() + i * 86400e3).toISOString().slice(0, 10);
}

// ---------- hydropower plant & river gauge modals ----------
function modalCtx() {
    if ($('kg-modal').classList.contains('active') && lastKGCtx) return { kind: 'kg', id: lastKGCtx.code };
    if ($('st-modal').classList.contains('active')) {
        if (currentShare.st) return { kind: 'gw', id: currentShare.st };
        if (currentShare.no3) return { kind: 'no3', id: currentShare.no3 };
    }
    if ($('hp-modal').classList.contains('active')) {
        if (currentShare.hp) return { kind: 'hp', id: currentShare.hp };
        if (currentShare.pg) return { kind: 'pg', id: currentShare.pg };
    }
    return null;
}
function hpPush(nextKind, nextId) {
    const c = modalCtx();
    if (c && !(c.kind === nextKind && c.id === String(nextId))) {
        hpStack.push(c);
        if (hpStack.length > 12) hpStack.shift();
    }
}
function hpBackGo() {
    const b = hpStack.pop();
    closeModal('hp-modal', true); destroyChart();
    if (!b) return;
    if (b.kind === 'kg') showKGModal(b.id, { noFly: true });
    else if (b.kind === 'gw' || b.kind === 'no3') stNavOpen(b.kind, b.id); // rebuilds ←-KG nav from lastKGCtx
    else if (b.kind === 'hp') hpOpen(b.id, true);
    else if (b.kind === 'pg') pgOpen(b.id, true);
}
function hpNavRender() {
    const nav = $('hp-topnav');
    const b = hpStack[hpStack.length - 1];
    if (b) {
        const lbl = b.kind === 'kg' ? (kgReg[b.id] ? kgReg[b.id].n : b.id)
            : b.kind === 'hp' ? ((plantProfiles && plantProfiles.plants[b.id]) || {}).name || b.id
            : b.kind === 'pg' ? 'gauge ' + b.id
            : 'station ' + b.id;
        nav.style.display = 'flex';
        nav.innerHTML = `<button class="modal-back" onclick="hpBackGo()">← ${esc(lbl)}</button>`;
    } else { nav.style.display = 'none'; nav.innerHTML = ''; }
}
async function hpOpen(pid, isBack) {
    if (!isBack) hpPush('hp', pid);
    const body = $('hp-modal-body');
    body.innerHTML = '<div style="text-align:center;padding:60px 0;"><div class="loading-spinner" style="margin:0 auto;"></div></div>';
    closeModal('kg-modal', true); closeModal('st-modal', true);
    openModal('hp-modal');
    try {
        if (!plantProfiles) plantProfiles = await fetch('data/plant_profiles.json').then(r => r.json());
    } catch (e) { body.innerHTML = '<p class="note">Plant data unavailable.</p>'; return; }
    const p = plantProfiles.plants[pid];
    if (!p) { body.innerHTML = '<p class="note">Unknown plant.</p>'; return; }
    destroyChart();
    currentShare = { hp: pid };
    updateURL();
    hpNavRender();

    const gen = p.gen.vals.filter(v => v != null);
    const last = gen.length ? gen[gen.length - 1] : null;
    const cf = p.mean_mwh_day_2026 != null ? Math.round(p.mean_mwh_day_2026 / (p.mw * 24) * 100) : null;
    const srcNote = p.release_source === 'a73'
        ? 'per-unit ENTSO-E data (A73)'
        : `downscaled from the national ${p.type.toLowerCase()} feed, calibrated on this plant's 2023–24 per-unit data (r = ${p.calib_r})`;
    const res = plantProfiles.reservoir;
    const showRes = p.psr !== 'ror';

    // downstream lists
    const gwRows = p.gw.map(l => `<div class="station-item" onclick="stOpenFromHp('gw','${esc(l.station)}')">
            <span class="dot" style="background:#8fb8f2"></span>
            <span class="nm">${esc(l.name)} <small style="color:#6a7194">well ${esc(l.station)}</small></span>
            <span class="meta">${l.km.toFixed(0)} km</span>
            <span class="val" title="partial R² = ${l.partial}, p = ${l.p}">${Math.round(l.partial * 100)}% <small style="color:#6a7194">${l.beta_sum > 0 ? '↑' : '↓'}</small></span>
        </div>`).join('');
    const pegRows = p.pegel.map(l => {
        const f = l.flow, s = l.sediment;
        const bits = [];
        if (f) bits.push(`flow ${f.mean_m3s} m³/s · <span style="color:${f.trend_pct_decade < -5 ? '#f28a7d' : f.trend_pct_decade > 5 ? '#7ed37e' : '#8b93b8'}">${f.trend_pct_decade > 0 ? '+' : ''}${f.trend_pct_decade}%/decade</span> (${f.years} yr)`);
        if (s) bits.push(`sediment ${Math.round(s.mean_daily_t)} t/day · ${s.trend_pct > 0 ? '+' : ''}${s.trend_pct}%`);
        return `<div class="station-item" style="display:block;" onclick="pgOpen('${esc(l.station)}')">
            <div style="display:flex;align-items:center;gap:8px;">
            <span class="dot" style="background:${l.sig ? '#facc6b' : '#3a3f55'}"></span>
            <span class="nm">${esc(l.name)} <small style="color:#6a7194">${esc(l.river)} · gauge ${esc(l.station)}</small></span>
            <span class="meta">${l.km.toFixed(0)} km</span>
            <span class="val" title="partial R² = ${l.partial}, p = ${l.p}${l.sig ? '' : ' — not significant'}">${l.sig ? Math.round(l.partial * 100) + '%' : '–'}</span>
            </div>
            ${bits.length ? `<div style="margin:2px 0 2px 20px;"><small style="color:#6a7194">${bits.join(' &nbsp;·&nbsp; ')}</small></div>` : ''}
        </div>`;
    }).join('');

    body.innerHTML = `
        <h2>${esc(p.name)}</h2>
        <div class="subtitle">${esc(p.type)} · ${esc(p.river)} · ENTSO-E · releases ${srcNote}</div>
        <div class="kv-grid kv3">
            <div class="kv"><div class="k">Capacity</div><div class="v">${p.mw} MW</div></div>
            <div class="kv"><div class="k">Mean output 2026</div><div class="v">${p.mean_mwh_day_2026 != null ? Math.round(p.mean_mwh_day_2026).toLocaleString('en') + ' MWh/d' : '–'}</div></div>
            <div class="kv" title="Mean 2026 output as a share of running at full capacity 24/7"><div class="k">Capacity factor</div><div class="v">${cf != null ? cf + '%' : '–'}</div></div>
        </div>
        <h3>Daily turbined energy${liveTag(lastDateOf(p.gen.d0, p.gen.vals), 10)} <small style="color:#6a7194;font-weight:400">last 12 months, MWh/day${p.release_source !== 'a73' ? ' · downscaled estimate' : ''}</small></h3>
        <div class="chart-box" style="height:170px;"><canvas id="hp-gen-chart"></canvas></div>
        <div class="note">Turbined energy is the proxy for water released downstream. Pumped-storage plants also consume
        energy to pump water back up (not shown); generation-side releases are what reach the river.</div>
        ${showRes ? `
        <h3>Austrian reservoir storage${liveTag(res.latest.date, 28)} <small style="color:#6a7194;font-weight:400">all AT hydro reservoirs, weekly</small></h3>
        <div class="kv-grid kv3">
            <div class="kv"><div class="k">Stored now (${esc(res.latest.date)})</div><div class="v">${res.latest.gwh.toLocaleString('en')} GWh</div></div>
            <div class="kv" title="Share of the historical maximum since 2015"><div class="k">of record max</div><div class="v">${res.latest.pct_of_max}%</div></div>
            <div class="kv" title="Rank of the current level among the same calendar weeks (±1) of ${res.latest.n_ref_years} previous observations since 2015"><div class="k">vs this week historically</div><div class="v">${res.latest.seasonal_percentile != null ? res.latest.seasonal_percentile + 'th pctl' : '–'}</div></div>
        </div>
        <div class="chart-box" style="height:150px;"><canvas id="hp-res-chart"></canvas></div>
        <div class="note">National figure (ENTSO-E publishes no per-reservoir storage) — context for how much water
        the storage fleet, including this plant's reservoirs, has left to release. Low storage in a dry summer means
        releases compete directly with residual river flow.</div>` : ''}
        ${p.gw.length ? `<h3>Downstream groundwater wells <small style="color:#6a7194;font-weight:400">significant coupling</small></h3>
        <div class="station-list">${gwRows}</div>` : ''}
        ${p.pegel.length ? `<h3>Downstream river gauges <small style="color:#6a7194;font-weight:400">OWF, along the river network</small></h3>
        <div class="station-list" style="max-height:260px;">${pegRows}</div>
        <div class="note">% = share of day-to-day river-stage variation explained by this plant's releases after
        controlling for precipitation (p&lt;0.01; grey dot = no significant link). Long-term flow and suspended-sediment
        trends are from OWF daily records — they reflect all drivers (climate, abstraction, regulation), not this plant alone.
        <b>Correlation, not proven causation.</b> <a href="#" onclick="showMethods();return false;">Details</a></div>` : ''}
        <div class="apirow">API: <code><a href="/llm/plant/${esc(pid)}" target="_blank">/llm/plant/${esc(pid)}</a></code></div>`;
    $('hp-modal-body').scrollTop = 0;
    hpDrawCharts(p, showRes ? res : null);
}
function hpDrawCharts(p, res) {
    const genEl = document.getElementById('hp-gen-chart');
    if (genEl) {
        const labels = [], vals = [];
        const d0 = new Date(p.gen.d0 + 'T00:00:00Z');
        for (let i = 0; i < p.gen.vals.length; i++) {
            const d = new Date(d0.getTime() + i * 86400e3);
            labels.push(d.toISOString().slice(0, 10));
            vals.push(p.gen.vals[i]);
        }
        chart = new Chart(genEl, {
            type: 'line',
            data: { labels, datasets: [{ data: vals, borderColor: 'rgba(143,184,242,0.9)', borderWidth: 1,
                pointRadius: 0, fill: true, backgroundColor: 'rgba(143,184,242,0.12)', tension: 0.1, spanGaps: false }] },
            options: { ...chartOpts('MWh'), scales: {
                x: { ticks: { color: '#6a7194', maxTicksLimit: 8, font: { size: 10 }, callback(v, i) { return labels[i] && labels[i].endsWith('-01') ? labels[i].slice(0, 7) : (i % 45 === 0 ? labels[i].slice(5) : null); } }, grid: { color: 'rgba(58,63,85,0.3)' } },
                y: { ticks: { color: '#6a7194', font: { size: 10 } }, grid: { color: 'rgba(58,63,85,0.3)' }, beginAtZero: true },
            } },
        });
    }
    const resEl = document.getElementById('hp-res-chart');
    if (resEl && res) {
        const labels = res.weekly.map(w => w[0]), vals = res.weekly.map(w => w[1]);
        popChart = new Chart(resEl, {
            type: 'line',
            data: { labels, datasets: [{ data: vals, borderColor: 'rgba(250,204,107,0.85)', borderWidth: 1.2,
                pointRadius: 0, fill: true, backgroundColor: 'rgba(250,204,107,0.08)', tension: 0.2 }] },
            options: { ...chartOpts('GWh'), scales: {
                x: { ticks: { color: '#6a7194', maxTicksLimit: 12, font: { size: 10 }, callback(v, i) { return labels[i] && labels[i].slice(5, 7) === '01' && labels[i].slice(8, 10) <= '07' ? labels[i].slice(0, 4) : null; } }, grid: { color: 'rgba(58,63,85,0.3)' } },
                y: { ticks: { color: '#6a7194', font: { size: 10 } }, grid: { color: 'rgba(58,63,85,0.3)' }, beginAtZero: true },
            } },
        });
    }
}

// ---------- river gauge modal (gauge_profiles.json) ----------
async function pgOpen(hzb, isBack) {
    if (!isBack) hpPush('pg', hzb);
    const body = $('hp-modal-body');
    body.innerHTML = '<div style="text-align:center;padding:60px 0;"><div class="loading-spinner" style="margin:0 auto;"></div></div>';
    closeModal('kg-modal', true); closeModal('st-modal', true);
    openModal('hp-modal');
    try {
        if (!gaugeProfiles) gaugeProfiles = await fetch('data/gauge_profiles.json').then(r => r.json());
    } catch (e) { body.innerHTML = '<p class="note">Gauge data unavailable.</p>'; return; }
    const g = gaugeProfiles.stations[hzb];
    if (!g) { body.innerHTML = '<p class="note">Unknown gauge.</p>'; return; }
    destroyChart();
    currentShare = { pg: hzb };
    updateURL();
    hpNavRender();

    const tr = g.trend_pct_decade;
    const trCol = tr == null ? '#8b93b8' : tr < -5 ? '#f28a7d' : tr > 5 ? '#7ed37e' : '#8b93b8';
    const liveLast = g.live ? lastDateOf(g.live.d0, g.live.vals) : null;
    // upstream plants with detected influence at this gauge
    const links = (plantInfl && plantInfl.pegel_links || []).filter(l => String(l.station) === String(hzb));
    links.sort((a, b) => (b.sig - a.sig) || (b.partial - a.partial));
    const plantRows = links.map(l => {
        const p = plantInfl.plants[l.plant] || {};
        return `<div class="station-item" onclick="hpOpen('${esc(l.plant)}')">
            <span class="dot" style="background:${l.sig ? '#facc6b' : '#3a3f55'}"></span>
            <span class="nm">${esc(p.name || l.plant)} <small style="color:#6a7194">${esc(p.type || '')} · ${p.mw || '?'} MW</small></span>
            <span class="meta">${l.km.toFixed(0)} km upstr.</span>
            <span class="val" title="partial R² = ${l.partial}, p = ${l.p}${l.sig ? '' : ' — not significant'}">${l.sig ? Math.round(l.partial * 100) + '%' : '–'}</span>
        </div>`;
    }).join('');

    body.innerHTML = `
        <h2>${esc(g.name)}</h2>
        <div class="subtitle">River gauge · ${esc(g.river)} · HZB ${esc(hzb)}${g.km2 ? ` · catchment ${g.km2.toLocaleString('en')} km²` : ''}</div>
        <div class="kv-grid kv3">
            <div class="kv"><div class="k">Mean flow</div><div class="v">${g.mean_m3s != null ? g.mean_m3s + ' m³/s' : '–'}</div></div>
            <div class="kv" title="Linear trend of annual mean flow over the full record"><div class="k">Flow trend</div><div class="v" style="color:${trCol}">${tr != null ? (tr > 0 ? '+' : '') + tr + '%/decade' : '–'}</div></div>
            <div class="kv" title="Suspended sediment transport (OWF Schwebstoff-Tagesfracht)"><div class="k">Sediment</div><div class="v">${g.sed ? Math.round(g.sed.t_day).toLocaleString('en') + ' t/d <small style=\"color:#6a7194\">' + (g.sed.trend_pct > 0 ? '+' : '') + g.sed.trend_pct + '%</small>' : '–'}</div></div>
        </div>
        ${g.live ? `<h3>Flow this year${liveTag(liveLast, 8)} <small style="color:#6a7194;font-weight:400">daily ${esc(g.live.param || 'flow').toLowerCase()}, ${esc(g.live.unit)}</small></h3>
        <div class="chart-box" style="height:160px;"><canvas id="pg-live-chart"></canvas></div>
        <div class="note">eHYD live feed (BML), refreshed daily.</div>` : ''}
        ${g.annual.length > 4 ? `<h3>Annual mean flow <small style="color:#6a7194;font-weight:400">${g.annual[0][0]}–${g.annual[g.annual.length - 1][0]}, m³/s</small></h3>
        <div class="chart-box" style="height:160px;"><canvas id="pg-annual-chart"></canvas></div>
        <div class="note">OWF hydrographic yearbook daily means, aggregated per year (years with ≥300 days).
        The long-term trend reflects all drivers — climate, abstraction, regulation.</div>` : ''}
        ${plantRows ? `<h3>Upstream hydropower <small style="color:#6a7194;font-weight:400">release signal at this gauge</small></h3>
        <div class="station-list">${plantRows}</div>
        <div class="note">% = share of day-to-day stage variation explained by the plant's turbined releases after
        controlling for precipitation (grey dot = no significant link). <b>Correlation, not proven causation.</b></div>` : ''}
        <div class="apirow">API: <code><a href="/llm/gauge/${esc(hzb)}" target="_blank">/llm/gauge/${esc(hzb)}</a></code></div>`;
    $('hp-modal-body').scrollTop = 0;

    const liveEl = document.getElementById('pg-live-chart');
    if (liveEl && g.live) {
        const d0 = new Date(g.live.d0 + 'T00:00:00Z');
        const labels = g.live.vals.map((_, i) => new Date(d0.getTime() + i * 86400e3).toISOString().slice(0, 10));
        chart = new Chart(liveEl, {
            type: 'line',
            data: { labels, datasets: [{ data: g.live.vals, borderColor: 'rgba(143,184,242,0.9)', borderWidth: 1.2,
                pointRadius: 0, fill: true, backgroundColor: 'rgba(143,184,242,0.12)', tension: 0.15, spanGaps: false }] },
            options: { ...chartOpts(g.live.unit), scales: {
                x: { ticks: { color: '#6a7194', maxTicksLimit: 8, font: { size: 10 }, callback: (v, i) => labels[i] && labels[i].endsWith('-01') ? labels[i].slice(5, 7) : null }, grid: { color: 'rgba(58,63,85,0.3)' } },
                y: { ticks: { color: '#6a7194', font: { size: 10 } }, grid: { color: 'rgba(58,63,85,0.3)' }, beginAtZero: true },
            } },
        });
    }
    const annEl = document.getElementById('pg-annual-chart');
    if (annEl && g.annual.length > 4) {
        popChart = new Chart(annEl, {
            type: 'line',
            data: { labels: g.annual.map(a => a[0]), datasets: [{ data: g.annual.map(a => a[1]),
                borderColor: 'rgba(79,195,247,0.8)', borderWidth: 1.5, pointRadius: 2,
                pointBackgroundColor: 'rgba(79,195,247,0.9)', fill: false, tension: 0.15 }] },
            options: chartOpts('m³/s'),
        });
    }
}

// ---------- groundwater body context (Wasserschatz 2021) ----------
function fmtM3(v) {
    if (v >= 1e9) return (v / 1e9).toFixed(1) + ' bn m\u00b3/yr';
    if (v >= 1e6) return (v / 1e6).toFixed(1) + ' M m\u00b3/yr';
    if (v >= 1e3) return Math.round(v / 1e3).toLocaleString('en') + ' k m\u00b3/yr';
    return Math.round(v) + ' m\u00b3/yr';
}
function useColor(pct) {
    return pct >= 40 ? '#f28a7d' : pct >= 20 ? '#f5cf6b' : '#7ed37e';
}
function useClass(pct) { return pct >= 40 ? 'high' : pct >= 20 ? 'mid' : 'low'; }
function gwkStyle(f) {
    const on = filt.use[useClass(f.properties.u)];
    return on
        ? { color: useColor(f.properties.u), weight: 1.2, opacity: 0.6, fill: true, fillOpacity: 0.03 }
        : { opacity: 0, fillOpacity: 0, weight: 0 };
}
function refreshGwk() { if (gwkLayer) gwkLayer.setStyle(gwkStyle); }
const SECTORS = [ // [key, label, color]
    ['supply', 'Drinking water supply', '#4fc3f7'],
    ['industry', 'Industry & trade', '#b48ce0'],
    ['irrigation', 'Irrigation', '#8fd08a'],
    ['livestock', 'Livestock', '#d8b455'],
    ['services', 'Services', '#8b93b8'],
];
function gwkHTML(kgCode) {
    if (!gwkCtx) return '';
    const gid = gwkCtx.kg2gwk[kgCode];
    const g = gid && gwkCtx.gwks[gid];
    if (!g) return '';
    const dem = g.demand || {};
    const total = g.demand_m3a || 1;
    let bars = '';
    for (const [key, label, color] of SECTORS) {
        const v = dem[key] || 0;
        if (!v) continue;
        const pct = v / total * 100;
        bars += `<div class="comp-row">
            <div class="comp-label">${label}</div>
            <div class="comp-bar"><div class="comp-fill" style="width:${Math.max(1, Math.round(pct))}%;background:${color}"></div></div>
            <div class="comp-val">${fmtM3(v)}<br><small style="color:#6a7194">${pct.toFixed(0)}%</small></div>
        </div>`;
    }
    const perCap = g.supply_lcd != null ?
        `<div class="kv" title="Public-supply groundwater abstraction divided by the ~${Math.round(g.population / 1000)}k residents of this body. Includes network losses, small business & public uses \u2014 compare to ~130 L/person/day household consumption (WAVE). Values far above that usually mean the body's waterworks also supply people living elsewhere (water export)."><div class="k">Supply abstraction/resident</div><div class="v">${Math.round(g.supply_lcd)} L/day${g.supply_lcd > 300 ? ' <small style="color:#6a7194;font-size:.72em">likely exports</small>' : ''}</div></div>` : '';
    return `<h3>The water body underneath <small style="color:#6a7194;font-weight:400">${esc(g.name)}</small></h3>
        <div class="kv-grid">
            <div class="kv" title="Total groundwater abstraction (wells + springs, all sectors) as % of the available resource. EEA WEI+ convention: \u226520% = water stress, \u226540% = severe stress. This is the 'Abstraction vs resource' GWI component."><div class="k">Use of resource</div><div class="v" style="color:${useColor(g.intensity_pct)}">${g.intensity_pct}%</div></div>
            <div class="kv" title="Available groundwater resource: sustainably usable share of recharge (mean 1998\u20132017)"><div class="k">Available resource</div><div class="v">${fmtM3(g.resource_m3a)}</div></div>
            <div class="kv"><div class="k">People on this body</div><div class="v">${g.population >= 1000 ? Math.round(g.population / 1000).toLocaleString('en') + 'k' : g.population}</div></div>
            ${perCap}
        </div>
        ${bars ? `<div style="margin-top:8px">${bars}</div>` : ''}
        <div class="note">${esc(g.aquifer)}, ${Math.round(g.area_km2).toLocaleString('en')} km\u00b2${g.group ? ' (group of bodies)' : ''}.
        Groundwater demand by sector, Wasserschatz \u00d6sterreichs (BMLRT 2021).${g.note ? ' ' + esc(g.note) + '.' : ''}
        <a href="#" onclick="showMethods();return false;">Details</a></div>`;
}

// ---------- population (Statistik Austria) ----------
function popForIso(iso) {
    if (!popData || iso == null) return null;
    let k = String(iso);
    if (popData.alias[k]) k = popData.alias[k];
    return popData.gemeinden[k] || null;
}
function popHTML(gem) {
    const r = gem ? popForIso(gem.iso) : null;
    if (!r) return '';
    const yrs = popData.years, n = yrs.length - 1;
    const now = r.t[n], first = r.t[0];
    const d = (now - first) / first * 100;
    const share65 = r.y65[n] / now * 100, share65f = r.y65[0] / r.t[0] * 100;
    const dcol = d > 2 ? '#7ec8e0' : d < -2 ? '#c98a9a' : '#7a8ac0';
    return `<h3>People on this water <small style="color:#6a7194;font-weight:400">Gemeinde ${esc(r.n)}, ${yrs[0]}–${yrs[n]}</small></h3>
        <div class="kv-grid">
            <div class="kv"><div class="k">Population ${yrs[n]}</div><div class="v">${now.toLocaleString('en')}</div></div>
            <div class="kv"><div class="k">Since ${yrs[0]}</div><div class="v" style="color:${dcol}">${d >= 0 ? '+' : ''}${d.toFixed(1)}%</div></div>
            <div class="kv" title="Share aged 65+ (was ${share65f.toFixed(0)}% in ${yrs[0]})"><div class="k">Aged 65+</div><div class="v">${share65.toFixed(0)}% <small style="color:#6a7194;font-size:.72em">was ${share65f.toFixed(0)}%</small></div></div>
            <div class="kv" title="Estimated household water demand: population × 130 L/person/day (ÖVGW average). Excludes industry, agriculture, tourism."><div class="k">Est. household demand</div><div class="v">${fmtDemand(now)}</div></div>
        </div>
        <div class="chart-box" style="height:110px;margin-top:8px;"><canvas id="pop-chart"></canvas></div>
        <div class="note">Population on Jan 1 (Statistik Austria, 2026 boundaries). Blue = total; dotted = aged 65+.
        Demand estimate uses the Austrian average of ~130 L/person/day household use — an indicator of how many people rely on local water, not measured abstraction.</div>`;
}
function fmtDemand(pop) {
    const m3yr = pop * 130 * 365 / 1000;
    if (m3yr >= 1e6) return (m3yr / 1e6).toFixed(1) + ' Mm³/yr';
    return Math.round(m3yr / 1000).toLocaleString('en') + 'k m³/yr';
}
function renderPopChart(gem) {
    const r = gem ? popForIso(gem.iso) : null;
    const ctx = document.getElementById('pop-chart');
    if (!r || !ctx) return;
    if (popChart) { popChart.destroy(); popChart = null; }
    popChart = new Chart(ctx, {
        type: 'line',
        data: { labels: popData.years, datasets: [
            { data: r.t, borderColor: 'rgba(79,195,247,0.9)', borderWidth: 1.5,
              pointRadius: 0, fill: false, tension: 0.15 },
            { data: r.y65, borderColor: 'rgba(245,207,107,0.8)', borderWidth: 1.2,
              borderDash: [4, 3], pointRadius: 0, fill: false, tension: 0.15 },
        ]},
        options: {
            responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
            plugins: { legend: { display: false }, tooltip: { callbacks: {
                label: c => (c.datasetIndex ? '65+: ' : 'total: ') + c.parsed.y.toLocaleString('en') } } },
            scales: {
                x: { ticks: { color: '#6a7194', maxTicksLimit: 7, font: { size: 9 } }, grid: { display: false } },
                y: { ticks: { color: '#6a7194', font: { size: 9 }, maxTicksLimit: 4 }, grid: { color: 'rgba(58,63,85,0.3)' } },
            },
        },
    });
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
            ${rec.no3 != null ? `<div class="kv" title="${NO3_TITLE}"><div class="k">Nitrate (interp.)</div><div class="v" style="color:${no3Tint(rec.no3)}">${rec.no3.toFixed(1)} mg/L <small style="color:#6a7194;font-weight:400;font-size:0.72em">${Math.round(rec.no3 / NO3_LIMIT * 100)}% of 50 mg/L</small></div></div>` : ''}
            ${rec.gw_trend != null ? `<div class="kv" title="${TREND_TITLE}"><div class="k">Level trend (interp.)</div><div class="v" style="color:${trendTint(rec.gw_trend)}">${fmtTrend(rec.gw_trend)}</div></div>` : ''}
        </div>
        ${popHTML(gem)}
        ${gwkHTML(code)}
        ${edoBarsHTML(gem)}
        ${hydroImpactHTML(hydroLinksForKG(code), true)}
        ${lat != null ? stationListHTML(lat, lon, 12.5) : ''}
        <div class="apirow">API: <code><a href="/llm/kg/${esc(code)}" target="_blank">/llm/kg/${esc(code)}</a></code></div>`;
    closeModal('st-modal', true);
    openModal('kg-modal');
    body.scrollTop = 0;
    renderPopChart(gem);
    lastKGCtx = { code, name: reg ? reg.n : code, lat, lon };
    currentShare = { kg: code };
    updateURL();
    if (!opts.noFly && lat != null && !map.getBounds().contains([lat, lon])) {
        map.flyTo([lat, lon], Math.max(map.getZoom(), 11), { duration: 0.8 });
    }
}

// ---------- station modals ----------
function destroyChart() {
    if (chart) { chart.destroy(); chart = null; }
    if (popChart) { popChart.destroy(); popChart = null; }
}
function closeModal(id, silent) {
    const ov = $(id);
    if (!ov.classList.contains('active') && silent) return;
    ov.classList.remove('active');
    if (id === 'st-modal') { stNav = null; renderStNav(); }
    if (id === 'hp-modal' && !silent) hpStack = [];
    if (!silent && (id === 'st-modal' || id === 'kg-modal' || id === 'hp-modal')) {
        destroyChart(); currentShare = {}; updateURL();
    }
}
function openModal(id) { $(id).classList.add('active'); }
// Tap outside the modal card = CLOSE (back to the map, discard nav stack).
// The ← button = BACK (pop one level). e.target can be the overlay itself or
// the .modal-wrap spacer flanking the card — both count as "outside".
document.querySelectorAll('.modal-overlay').forEach(ov =>
    ov.addEventListener('click', e => {
        if (e.target === ov || e.target.classList.contains('modal-wrap')) closeModal(ov.id);
    }));
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') document.querySelectorAll('.modal-overlay.active').forEach(ov => closeModal(ov.id));
    if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && $('st-modal').classList.contains('active') && stNav) {
        e.preventDefault();
        stNavStep(e.key === 'ArrowRight' ? 1 : -1);
    }
});

function openGWStationById(id) { const s = gwStations.find(x => String(x.id) === String(id)); if (s) openGWStation(s); }
function openNO3StationById(id) { const s = no3Stations.find(x => String(x.id) === String(id)); if (s) openNO3Station(s); }

// ---------- station browsing (KG -> stations, prev/next, back) ----------
function buildStNav(kind, id) {
    if (!lastKGCtx || lastKGCtx.lat == null) return null;
    const { gws, n3s } = nearStations(lastKGCtx.lat, lastKGCtx.lon, 12.5);
    const items = [
        ...gws.map(({ s }) => ({ k: 'gw', id: String(s.id), name: s.name })),
        ...n3s.map(({ s }) => ({ k: 'no3', id: String(s.id), name: 'NO\u2083 ' + s.id })),
    ];
    const back = { kind: 'kg', id: lastKGCtx.code, label: lastKGCtx.name };
    const idx = items.findIndex(it => it.k === kind && it.id === String(id));
    if (idx < 0) return { back, items: [], idx: -1 }; // back only
    return { back, items, idx };
}
function stNavSync(kind, id) {
    if (!stNav) return;
    const i = stNav.items.findIndex(it => it.k === kind && it.id === String(id));
    if (i >= 0) stNav.idx = i;
    else if (stNav.items.length) stNav = { back: stNav.back, items: [], idx: -1 };
}
function stNavOpen(kind, id) {
    stNav = buildStNav(kind, id);
    (kind === 'gw' ? openGWStationById : openNO3StationById)(id);
}
// open a station from the plant/gauge modal: back goes to that modal, not a KG
function stOpenFromHp(kind, id) {
    const c = modalCtx();
    if (c && (c.kind === 'hp' || c.kind === 'pg')) {
        const label = c.kind === 'hp'
            ? (((plantProfiles && plantProfiles.plants[c.id]) || (plantInfl && plantInfl.plants[c.id]) || {}).name || c.id)
            : 'gauge ' + c.id;
        stNav = { back: { kind: c.kind, id: c.id, label }, items: [], idx: -1 };
    } else {
        stNav = buildStNav(kind, id);
    }
    (kind === 'gw' ? openGWStationById : openNO3StationById)(id);
}
function stNavStep(dir) {
    if (!stNav || !stNav.items.length) return;
    const n = stNav.items.length;
    stNav.idx = (stNav.idx + dir + n) % n;
    const it = stNav.items[stNav.idx];
    (it.k === 'gw' ? openGWStationById : openNO3StationById)(it.id);
    const s = (it.k === 'gw' ? gwStations : no3Stations).find(x => String(x.id) === it.id);
    if (s && !map.getBounds().contains([s.lat, s.lon])) map.panTo([s.lat, s.lon], { duration: 0.5 });
}
function stNavBack() {
    if (!stNav || !stNav.back) return;
    const b = stNav.back;
    closeModal('st-modal', true);
    destroyChart();
    if (b.kind === 'kg') showKGModal(b.id, { noFly: true });
    else if (b.kind === 'hp') hpOpen(b.id, true);
    else if (b.kind === 'pg') pgOpen(b.id, true);
}
function renderStNav() {
    const nav = $('st-topnav'), prev = $('st-prev'), next = $('st-next');
    if (!nav) return;
    if (stNav) {
        const many = stNav.items.length > 1;
        nav.style.display = 'flex';
        nav.innerHTML = `
            <button class="modal-back" onclick="stNavBack()" title="Back to ${esc(stNav.back.label)}">← ${esc(stNav.back.label)}</button>` +
            (many ? `<span class="mnav-pos">station ${stNav.idx + 1} / ${stNav.items.length} near this KG · ← → keys</span>` : '');
        prev.style.display = next.style.display = many ? 'flex' : 'none';
    } else {
        nav.style.display = 'none'; nav.innerHTML = '';
        prev.style.display = next.style.display = 'none';
    }
}
$('st-prev').addEventListener('click', () => stNavStep(-1));
$('st-next').addEventListener('click', () => stNavStep(1));

function openGWStation(s) {
    destroyChart();
    const t = s.trend_m_per_decade;
    const status = t == null ? '–' : t < -0.05 ? 'Declining' : t > 0.05 ? 'Rising' : 'Stable';
    const body = $('st-modal-body');
    body.innerHTML = `
        <h2>${esc(s.name)}</h2>
        <div class="subtitle">eHYD groundwater level station · ID ${esc(s.id)}${s.start_year ? ` · ${s.start_year}–${s.end_year}` : ''}</div>
        <div class="kv-grid kv3">
            <div class="kv" title="${TREND_TITLE}"><div class="k">10-yr trend</div><div class="v" style="color:${trendTint(t)}">${fmtTrend(t, 1)}</div></div>
            <div class="kv"><div class="k">Status</div><div class="v">${status}</div></div>
            <div class="kv"><div class="k">p-value (10-yr)</div><div class="v">${s.p_value_10yr != null ? (s.p_value_10yr < 0.001 ? '<0.001' : s.p_value_10yr.toFixed(3)) : (s.p_value != null ? s.p_value.toFixed(3) : '–')}</div></div>
            <div class="kv" title="${TREND_TITLE}"><div class="k">Full-period trend</div><div class="v">${s.trend_full_period != null ? fmtTrend(s.trend_full_period, 1) : '–'}</div></div>
            <div class="kv"><div class="k">Mean level</div><div class="v">${s.mean_level != null ? s.mean_level.toFixed(2) + ' m' : '–'}</div></div>
            <div class="kv"><div class="k">Current level</div><div class="v">${s.current_level != null ? s.current_level.toFixed(2) + ' m' : '–'}</div></div>
        </div>
        <h3>Level history <small style="color:#6a7194;font-weight:400">annual means, m above Adriatic</small></h3>
        <div class="chart-box" id="st-chart-box"><div style="text-align:center;padding-top:80px;"><div class="loading-spinner" style="margin:0 auto;"></div></div></div>
        <div class="note">Points from the last 10 years (red) drive the trend used in the GWI. Source: eHYD (BML).</div>
        ${hydroImpactHTML(hydroLinksForStation(s.id), false)}
        <div class="apirow">API: <code><a href="/llm/point/gw:${esc(s.id)}" target="_blank">/llm/point/gw:${esc(s.id)}</a></code></div>`;
    closeModal('kg-modal', true); closeModal('hp-modal', true);
    stNavSync('gw', s.id);
    renderStNav();
    openModal('st-modal');
    $('st-modal-body').scrollTop = 0;
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

// WFD/GWD assessment for a nitrate station: quality standard 50 mg/L,
// trend-reversal trigger at 75% of it (37.5 mg/L) when the trend is rising.
function no3WFDBadge(latest, trendPerYr) {
    if (latest == null) return '';
    const rising = trendPerYr != null && trendPerYr > 0.05; // > +0.5 mg/L per decade
    if (latest >= NO3_LIMIT)
        return `<span class="badge stressed" title="${NO3_TITLE}">⚠ above 50 mg/L standard</span>`;
    if (latest >= NO3_TREND_REVERSAL && rising)
        return `<span class="badge stressed" title="${NO3_TITLE}">≥ 37.5 mg/L &amp; rising → WFD trend reversal due</span>`;
    if (latest >= NO3_TREND_REVERSAL)
        return `<span class="badge watch" title="${NO3_TITLE}">above 37.5 mg/L WFD trend-reversal threshold</span>`;
    if (rising && latest >= 25)
        return `<span class="badge watch" title="${NO3_TITLE}">below thresholds, but rising</span>`;
    return `<span class="badge good" title="${NO3_TITLE}">below WFD thresholds</span>`;
}

function openNO3Station(s) {
    destroyChart();
    const overLimit = s.latest != null && s.latest >= NO3_LIMIT;
    const trend = s.trend_per_yr;
    const body = $('st-modal-body');
    body.innerHTML = `
        <h2>Nitrate station ${esc(s.id)}</h2>
        <div class="subtitle">EEA WISE-6 groundwater quality · ${s.first_year}–${s.last_year} · ${s.n_samples} samples</div>
        <div style="margin:0 0 10px;">${no3WFDBadge(s.latest, trend)}</div>
        <div class="kv-grid">
            <div class="kv"><div class="k">Latest NO₃ (${s.latest_year})</div><div class="v" style="color:${no3Tint(s.latest)}">${s.latest != null ? s.latest.toFixed(1) + ' mg/L' : '–'}</div></div>
            <div class="kv" title="${NO3_TITLE}"><div class="k">vs 50 mg/L standard</div><div class="v">${s.latest != null ? Math.round(s.latest / NO3_LIMIT * 100) + '%' : '–'}${overLimit ? ' ⚠' : ''}</div></div>
            <div class="kv"><div class="k">Mean (all years)</div><div class="v">${s.mean != null ? s.mean.toFixed(1) + ' mg/L' : '–'}</div></div>
            <div class="kv" title="Linear trend of the annual means, expressed as change per 10 years"><div class="k">Trend</div><div class="v">${trend != null ? (trend > 0 ? '+' : '') + (trend * 10).toFixed(1) + ' mg/L per decade' : '–'}</div></div>
        </div>
        <h3>Nitrate history <small style="color:#6a7194;font-weight:400">annual means, mg/L</small></h3>
        <div class="chart-box" id="st-chart-box"></div>
        <div class="note"><span style="color:#e05252">——</span> 50 mg/L EU groundwater quality standard ·
        <span style="color:#f39c12">––</span> 45 mg/L Austrian target ·
        <span style="color:#d8b455">···</span> 37.5 mg/L WFD trend-reversal threshold (75% of the standard — if concentrations rise above it, the Water Framework/Groundwater Directive requires measures to reverse the trend).
        Values below LOQ counted as LOQ/2. Source: EEA Waterbase ICM.</div>
        <div class="apirow">API: <code><a href="/llm/point/no3:${esc(s.id)}" target="_blank">/llm/point/no3:${esc(s.id)}</a></code></div>`;
    closeModal('kg-modal', true); closeModal('hp-modal', true);
    stNavSync('no3', s.id);
    renderStNav();
    openModal('st-modal');
    $('st-modal-body').scrollTop = 0;
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
            { data: years.map(() => NO3_LIMIT), borderColor: 'rgba(224,82,82,0.65)', borderWidth: 1.2, borderDash: [6, 4], pointRadius: 0 },
            { data: years.map(() => NO3_AT_TARGET), borderColor: 'rgba(243,156,18,0.4)', borderWidth: 1, borderDash: [3, 4], pointRadius: 0 },
            { data: years.map(() => NO3_TREND_REVERSAL), borderColor: 'rgba(216,180,85,0.4)', borderWidth: 1, borderDash: [1.5, 3.5], pointRadius: 0 },
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
    wireLegend();
}

// ---------- interactive legend ----------
function wireLegend() {
    const tap = (el, fn) => {
        el.addEventListener('click', e => {
            e.preventDefault(); e.stopPropagation();
            fn(); syncLegendUI(); updateURL();
            el.classList.remove('leg-pop'); void el.offsetWidth; // restart animation
            el.classList.add('leg-pop');
        });
        el.style.cursor = 'pointer';
    };
    document.querySelectorAll('[data-cat]').forEach(el =>
        tap(el, () => { filt.cat[el.dataset.cat] = !filt.cat[el.dataset.cat]; refreshChoropleth(); }));
    document.querySelectorAll('[data-trend]').forEach(el =>
        tap(el, () => { filt.trend[el.dataset.trend] = !filt.trend[el.dataset.trend]; applyStationFilters(); }));
    document.querySelectorAll('[data-band]').forEach(el =>
        tap(el, () => { const i = +el.dataset.band; filt.no3[i] = !filt.no3[i]; applyStationFilters(); }));
    document.querySelectorAll('[data-use]').forEach(el =>
        tap(el, () => { filt.use[el.dataset.use] = !filt.use[el.dataset.use]; refreshGwk(); }));
    syncLegendUI();
}
// One-time staggered pop when a sublegend opens, so people discover the chips are filters.
function hintChips(container) {
    if (container._hinted) return;
    container._hinted = true;
    container.querySelectorAll('.leg-btn').forEach((el, i) =>
        setTimeout(() => { el.classList.add('leg-pop'); setTimeout(() => el.classList.remove('leg-pop'), 350); }, 120 + i * 90));
}
function syncLegendUI() {
    document.querySelectorAll('[data-cat]').forEach(el => el.classList.toggle('leg-off', !filt.cat[el.dataset.cat]));
    document.querySelectorAll('[data-trend]').forEach(el => el.classList.toggle('leg-off', !filt.trend[el.dataset.trend]));
    document.querySelectorAll('[data-band]').forEach(el => el.classList.toggle('leg-off', !filt.no3[+el.dataset.band]));
    document.querySelectorAll('[data-use]').forEach(el => el.classList.toggle('leg-off', !filt.use[el.dataset.use]));
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
    for (const k of ['kg', 'st', 'no3', 'gem', 'hp', 'pg']) if (currentShare[k]) p.set(k, currentShare[k]);
    // layer toggles (default: gw on, no3+gwk off) — only encode when non-default
    const ly = [];
    if ($('tg-gw').checked) ly.push('gw');
    if ($('tg-no3').checked) ly.push('no3');
    if ($('tg-gwk').checked) ly.push('gwk');
    if (ly.join(',') !== 'gw') p.set('ly', ly.join(',') || 'none');
    // legend filters — encode hidden classes only
    const hc = Object.keys(filt.cat).filter(k => !filt.cat[k]);
    const ht = Object.keys(filt.trend).filter(k => !filt.trend[k]);
    const hn = filt.no3.map((v, i) => v ? null : i).filter(v => v != null);
    const hu = Object.keys(filt.use).filter(k => !filt.use[k]);
    if (hc.length) p.set('hc', hc.join(','));
    if (ht.length) p.set('ht', ht.join(','));
    if (hn.length) p.set('hn', hn.join(','));
    if (hu.length) p.set('hu', hu.join(','));
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
    // layer toggles
    if (p.get('ly') != null) {
        const ly = p.get('ly') === 'none' ? [] : p.get('ly').split(',');
        for (const [param, id] of [['gw', 'tg-gw'], ['no3', 'tg-no3'], ['gwk', 'tg-gwk']]) {
            const want = ly.includes(param), el = $(id);
            if (el.checked !== want) { el.checked = want; el.dispatchEvent(new Event('change')); }
        }
    }
    // legend filters (hidden classes)
    let refilter = false;
    if (p.get('hc')) { for (const k of p.get('hc').split(',')) if (k in filt.cat) { filt.cat[k] = false; } refreshChoropleth(); refilter = true; }
    if (p.get('ht')) { for (const k of p.get('ht').split(',')) if (k in filt.trend) filt.trend[k] = false; refilter = true; }
    if (p.get('hn')) { for (const k of p.get('hn').split(',')) { const i = +k; if (i >= 0 && i < filt.no3.length) filt.no3[i] = false; } refilter = true; }
    if (p.get('hu')) { for (const k of p.get('hu').split(',')) if (k in filt.use) filt.use[k] = false; refreshGwk(); refilter = true; }
    if (refilter) { applyStationFilters(); syncLegendUI(); }
    const v = p.get('v');
    if (v) {
        const [lat, lng, z] = v.split(',').map(Number);
        if (isFinite(lat) && isFinite(lng)) map.setView([lat, lng], isFinite(z) ? z : 9, { animate: false });
    }
    if (p.get('kg') && kgReg[p.get('kg')]) showKGModal(p.get('kg'), { noFly: !v });
    else if (p.get('hp')) hpOpen(p.get('hp'));
    else if (p.get('pg')) pgOpen(p.get('pg'));
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
    <div class="subtitle">What this map shows and how it is computed. Generated ${esc(gwiMeta.generated)}.</div>

    <h3>The Groundwater Status Index (GWI)</h3>
    <p>One number per Katastralgemeinde (KG), <b>0 = good → 1 = stressed</b>, computed at 7,850 KG centroids
    and averaged per Gemeinde for the map colour. A weighted mean of six sub-risks, each clamped to 0–1;
    weights renormalize over the components actually available, so missing data is never counted as zero risk.</p>
    <ul>
        <li><b>Level trend — 30%.</b> IDW mean of the 10-year level trend of eHYD stations ≤ 12.5 km
            (fallback nearest-3 ≤ 30 km, flagged <i>◌ estimated</i>). Max risk at −0.5 m/decade.</li>
        <li><b>Nitrate — 20%.</b> IDW mean of the latest annual-mean NO₃ (stations reporting since ≥ 2015).
            Risk = latest / 50 mg/L. Anchors: <b>50</b> = EU quality standard (GWD 2006/118/EC),
            <b>37.5</b> = trend-reversal threshold (75%), <b>45</b> = Austrian QZV target.</li>
        <li><b>Abstraction vs resource — 15%.</b> Groundwater-body <i>Nutzungsintensität</i>: total abstraction
            (supply, irrigation, livestock, industry, services) ÷ available resource, from Wasserschatz
            Österreichs 2021. Max risk at 40% (EEA WEI+ convention: ≥ 20% stress, ≥ 40% severe).
            Demand pressure, not observed state.</li>
        <li><b>Drought pressure — 15%.</b> Copernicus EDO Combined Drought Indicator, Gemeinde mean 2012–2023.</li>
        <li><b>Precipitation divergence — 10%.</b> How far the 5-year level sits below what local precipitation
            would explain (residual in σ). Persistent deficits suggest abstraction/structural loss, not weather.</li>
        <li><b>WFD status — 10%.</b> WISE 2022 chemical + ecological status of monitored water bodies.</li>
    </ul>
    <p>Categories: <span class="badge good">good</span> &lt; 0.30 ≤ <span class="badge watch">watch</span>
    &lt; 0.50 ≤ <span class="badge stressed">stressed</span> — calibrated to the national distribution
    (~23 / 42 / 35%), i.e. relative context, not regulatory judgements.</p>

    <h3>Map layers</h3>
    <ul>
        <li><b>Level stations</b> — 3,732 eHYD wells, coloured by 10-year trend (falling / stable / rising).</li>
        <li><b>Nitrate stations</b> — 2,250 EEA WISE-6 stations, continuous blue→red scale anchored at the
            WFD thresholds. Toggling this also shades each <b>groundwater body</b> by the median of its
            recent (≥ 2015) stations — the aquifer-scale picture behind the dots.</li>
        <li><b>Water bodies &amp; use</b> — the 129 NGP-2015 groundwater bodies outlined by abstraction
            intensity (Wasserschatz 2021).</li>
        <li>The legend is interactive: click <i>good/watch/stressed</i>, trend classes or nitrate bands to
            filter the map; all toggles are encoded in the share link.</li>
    </ul>

    <h3>Hydropower influence (informational, not in the GWI)</h3>
    <p>Some station/KG views show statistically significant coupling between an upstream hydro plant's daily
    releases (ENTSO-E per-unit generation) and a downstream well's day-to-day level changes. Wells are matched
    along the actual OSM river network (≤ 120 km downstream, ≤ 4 km lateral); the effect is a partial R² over a
    precipitation-controlled regression, reported only if p &lt; 0.01, R² ≥ 5% and above a 60-day placebo.
    This is correlation with controls, <b>not proven causation</b>, which is why it is displayed but never
    folded into the index.</p>

    <h3>Data sources</h3>
    <ul>
        <li><b>eHYD (BML)</b> — groundwater levels, annual means, most 1966–2022.</li>
        <li><b>EEA Waterbase ICM 2026 (WISE-6)</b> — nitrate 1992–2024; <b>WISE WFD 2022</b> — body status.</li>
        <li><b>Wasserschatz Österreichs</b> (BMLRT/Umweltbundesamt 2021) — per-body resource &amp; demand;
            GWK boundaries INSPIRE NGP-2015.</li>
        <li><b>Copernicus EDO</b> — Combined Drought Indicator 2012–2023, aggregated per Gemeinde.</li>
        <li><b>NASA POWER</b> — daily precipitation (0.5°) behind the divergence component.</li>
        <li><b>Statistik Austria OGD</b> — KG/Gemeinde registry &amp; boundaries (CC-BY-4.0) and population
            2002–2026 behind the “people on this water” section.</li>
        <li><b>ENTSO-E Transparency</b> — hydro generation behind the hydropower section.</li>
        <li><b>OSM/Geofabrik</b> — directed waterway network for plant→well matching.</li>
    </ul>

    <h3>Honest limitations</h3>
    <ul>
        <li><b>Interpolation is not measurement</b> — between stations the index is an IDW estimate; Alpine
            coverage is sparse (◌ marks the nearest-3 fallback).</li>
        <li><b>Aquifers ignore administrative borders</b> — treat sharp colour steps between neighbouring
            KGs with skepticism.</li>
        <li>WFD status is per water body; its Gemeinde attribution is approximate.</li>
        <li>Values below the limit of quantification count as LOQ/2 — very clean stations may be slightly
            overstated.</li>
        <li>Trend windows differ per station (most level records end 2020–2022; nitrate runs to 2024).</li>
        <li>The Gemeinde colour is the mean over its KGs — tap the map for KG-level values.</li>
    </ul>

    <h3>Reproducibility &amp; API</h3>
    <p><code>scripts/build_gw_index.py</code> computes the index; per-KG values are served at
    <code>/llm/kg/{kg_code}</code> (<a href="/llm/manifest.json" target="_blank">manifest</a>).
    Data license CC-BY-4.0; sources retain their own terms.</p>`;
    openModal('methods-modal');
}

// ---------- start ----------
boot().catch(e => {
    $('loading-overlay').innerHTML = '<div class="t">Failed to load</div><div class="s">' + esc(e.message) + '</div>';
    console.error(e);
});
