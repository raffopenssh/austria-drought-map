#!/usr/bin/env python3
"""Simple HTTP server with gzip support for pre-compressed files."""

import http.server
import os
import urllib.parse
import sys

class GzipHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory='web', **kwargs)
    
    def end_headers(self):
        # Add CORS headers
        self.send_header('Access-Control-Allow-Origin', '*')
        # Add cache headers for static assets
        path = urllib.parse.urlparse(self.path).path
        if path.endswith(('.json', '.geojson', '.js', '.css')):
            self.send_header('Cache-Control', 'public, max-age=3600')
        super().end_headers()
    
    def do_GET(self):
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
