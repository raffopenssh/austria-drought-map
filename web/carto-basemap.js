// ---------------------------------------------------------------------------
// CARTO basemap snippet — copy this file (or just the block below) into any
// simple Leaflet map app.
//
//   <script src="carto-basemap.js"></script>
//   const map = L.map('map').setView([47.6, 13.5], 7);
//   cartoBasemap('dark_all').addTo(map);      // or 'voyager', 'positron', ...
//
// Styles: voyager | positron | dark_all | dark_matter | light_all | rastertiles/voyager
// The key must be appended as ?key=... or CARTO stamps an "API key required"
// watermark on the tiles. If the watermark lingers after adding the key,
// hard-refresh (Ctrl/Cmd+Shift+R) — browser and CDN both cache tiles.
// ---------------------------------------------------------------------------
const CARTO_KEY = 'cb1_2f4r_1_641ea85562265ec4220f53fc';

function cartoBasemap(style = 'voyager', opts = {}) {
  return L.tileLayer(
    `https://{s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}{r}.png?key=${CARTO_KEY}`,
    Object.assign({
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 20,
    }, opts)
  );
}

// Plain one-liner version (no helper):
// L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png?key=cb1_2f4r_1_641ea85562265ec4220f53fc', {
//   attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, &copy; <a href="https://carto.com/attributions">CARTO</a>',
//   subdomains: 'abcd', maxZoom: 20
// }).addTo(map);
