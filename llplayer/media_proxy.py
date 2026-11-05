"""Loopback media transport for extractor-provided headers and HTTP byte ranges.

Only opaque, registered resource paths are served. This is not an open proxy.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import secrets
import threading
from urllib.parse import urljoin, urlparse
import httpx


class MediaProxy:
    def __init__(self):
        self.routes = {}
        self.lock = threading.Lock()
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass  # Media URLs and headers can contain temporary credentials.

            def do_HEAD(self):
                self.deliver(True)

            def do_GET(self):
                self.deliver(False)

            def deliver(self, head):
                with owner.lock:
                    route = owner.routes.get(self.path.split('?', 1)[0])
                if route is None:
                    self.send_error(404)
                    return
                url, headers = route
                request_headers = dict(headers, **{'Accept-Encoding': 'identity'})
                if self.headers.get('Range'):
                    request_headers['Range'] = self.headers['Range']
                try:
                    with httpx.Client(timeout=30, follow_redirects=True) as client:
                        with client.stream('HEAD' if head else 'GET', url, headers=request_headers) as response:
                            playlist = 'mpegurl' in response.headers.get('Content-Type', '').lower() or urlparse(str(response.url)).path.lower().endswith('.m3u8')
                            if playlist and not head and response.is_success:
                                content = response.read().decode('utf-8-sig')
                                rewritten = []
                                def resource(value):
                                    target = urljoin(str(response.url), value)
                                    # Do not propagate sensitive origin-specific headers to a
                                    # different host named by an untrusted playlist.
                                    selected = dict(headers)
                                    if urlparse(target).netloc != urlparse(url).netloc:
                                        selected = {k:v for k,v in selected.items() if k.lower() not in ('authorization','cookie')}
                                    return owner.url_for(target, selected) if target.startswith(('http://','https://')) else value
                                for line in content.splitlines():
                                    if line and not line.startswith('#'):
                                        line = resource(line.strip())
                                    elif 'URI="' in line:
                                        line = re.sub(r'URI="([^"]+)"', lambda m: 'URI="' + resource(m.group(1)) + '"', line)
                                    rewritten.append(line)
                                data = ('\n'.join(rewritten) + '\n').encode()
                                self.send_response(response.status_code)
                                self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
                                self.send_header('Content-Length', str(len(data)))
                                self.end_headers()
                                self.wfile.write(data)
                                return
                            self.send_response(response.status_code)
                            for name in ('Content-Type','Content-Length','Content-Range','Accept-Ranges','Content-Encoding'):
                                if name in response.headers:
                                    self.send_header(name, response.headers[name])
                            self.end_headers()
                            if not head:
                                for chunk in response.iter_raw():
                                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except (httpx.HTTPError, OSError):
                    self.close_connection = True
                    # No raw URL, authentication header or response body is exposed.
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def url_for(self, target, headers=None):
        # FFmpeg's HLS demuxer checks segment filename extensions before opening
        # them. Preserve a safe media suffix while keeping the origin opaque.
        from pathlib import PurePosixPath
        suffix = PurePosixPath(urlparse(target).path).suffix.lower()
        allowed = {'.m3u8', '.m3u', '.ts', '.m4s', '.mp4', '.m4a', '.mp3', '.aac', '.ac3', '.ec3', '.vtt', '.webvtt', '.key', '.bin', '.webm', '.mkv', '.ogg', '.oga', '.ogv', '.wav'}
        path = '/' + secrets.token_urlsafe(24) + (suffix if suffix in allowed else '.ts')
        with self.lock:
            self.routes[path] = (target, dict(headers or {}))
        return f'http://127.0.0.1:{self.server.server_port}{path}'

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        with self.lock:
            self.routes.clear()
