#!/usr/bin/env python3
"""Simple HTTP server with gzip support for pre-compressed files."""

import http.server
import json
import os
import re
import urllib.parse
import sys

import llm_api

class GzipHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory='web', **kwargs)
    
    def end_headers(self):
        # Add CORS headers
        self.send_header('Access-Control-Allow-Origin', '*')
        # Add cache headers for static assets
        path = urllib.parse.urlparse(self.path).path
        if path.endswith(('.html', '/')) or path == '':
            # HTML must always be revalidated, otherwise phones keep an old
            # document whose ?v= cache-buster points at a stale app.js.
            self.send_header('Cache-Control', 'no-cache')
        elif path.endswith(('.js', '.css')):
            # Revalidate code too; Last-Modified makes this a cheap 304.
            self.send_header('Cache-Control', 'no-cache')
        elif path.endswith(('.json', '.geojson')):
            self.send_header('Cache-Control', 'public, max-age=3600')
        super().end_headers()
    
    def _send_json(self, status, obj):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, url_path):
        name = 'index.html' if url_path in ('/', '/index.html') else url_path.lstrip('/')
        fs_path = os.path.join('web', name)
        try:
            with open(fs_path, 'r', encoding='utf-8') as f:
                html = f.read()
        except OSError:
            self.send_error(404)
            return

        def stamp(m):
            asset = m.group(1)
            try:
                ver = int(os.path.getmtime(os.path.join('web', asset)))
            except OSError:
                return m.group(0)
            return f'{asset}?v={ver}'

        html = re.sub(r'\b(app\.js|explore\.js|[\w./-]+\.css)(?:\?v=[^"\']*)?', stamp, html)
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_GET(self):
        parsed_full = urllib.parse.urlparse(self.path)
        # Sibling-service integration endpoints (/llm/...)
        if parsed_full.path.startswith('/llm/'):
            try:
                query = urllib.parse.parse_qs(parsed_full.query)
                routed = llm_api.handle(parsed_full.path, query)
            except Exception as exc:  # never 500 silently
                self._send_json(500, {'error': 'internal_error', 'detail': str(exc)})
                return
            if routed is not None:
                status, obj = routed
                self._send_json(status, obj)
                return

        # HTML: stamp asset URLs with the file mtime so the cache-buster can
        # never drift out of sync with the deployed JS/CSS (a manual ?v=N bump
        # was forgotten once, leaving phones on JS without new handlers).
        if parsed_full.path in ('/', '/index.html', '/explore.html'):
            self._send_html(parsed_full.path)
            return

        # Repo-root LICENSE (code MIT, derived data CC BY 4.0), linked from the footer.
        if parsed_full.path in ('/LICENSE', '/license'):
            body = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'LICENSE'), 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Check if client accepts gzip
        accept_encoding = self.headers.get('Accept-Encoding', '')
        
        if 'gzip' in accept_encoding:
            # Parse the path (remove query string)
            parsed = urllib.parse.urlparse(self.path)
            clean_path = parsed.path
            
            # Translate to filesystem path
            fs_path = self.translate_path(clean_path)
            gz_path = fs_path + '.gz'
            
            if os.path.exists(gz_path) and os.path.isfile(gz_path):
                # Serve gzipped version
                self.send_response(200)
                
                # Determine content type
                if fs_path.endswith('.json'):
                    self.send_header('Content-Type', 'application/json')
                elif fs_path.endswith('.geojson'):
                    self.send_header('Content-Type', 'application/geo+json')
                else:
                    self.send_header('Content-Type', 'application/octet-stream')
                
                self.send_header('Content-Encoding', 'gzip')
                self.send_header('Content-Length', os.path.getsize(gz_path))
                self.end_headers()
                
                with open(gz_path, 'rb') as f:
                    self.wfile.write(f.read())
                return
        
        # Fall back to normal handling
        super().do_GET()

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    
    server = http.server.HTTPServer(('', port), GzipHTTPRequestHandler)
    print(f'Serving on port {port} with gzip support...', flush=True)
    server.serve_forever()
