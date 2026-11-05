from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import httpx
import pytest
from llplayer.media_proxy import MediaProxy
from llplayer import services


@pytest.fixture
def origin():
    media = Path(__file__).parents[1] / 'artifacts/test-video.mp4'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_HEAD(self):
            self.deliver(True)
        def do_GET(self):
            self.deliver(False)
        def deliver(self, head):
            if self.headers.get('X-Media-Token') != 'test-token':
                self.send_error(403)
                return
            data = b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\nclip.ts\n' if self.path == '/list.m3u8' else media.read_bytes()
            if self.path.startswith('/stream'):
                data = (media.parent / Path(self.path).name).read_bytes()
            start, end = 0, len(data)-1
            partial = self.headers.get('Range', '')
            if partial:
                first, last = partial.removeprefix('bytes=').split('-')
                start, end = int(first), int(last) if last else end
            self.send_response(206 if partial else 200)
            self.send_header('Content-Type', 'application/vnd.apple.mpegurl' if self.path.endswith('m3u8') else 'video/mp4')
            self.send_header('Content-Length', str(end-start+1))
            self.send_header('Accept-Ranges', 'bytes')
            if partial:
                self.send_header('Content-Range', f'bytes {start}-{end}/{len(data)}')
            self.end_headers()
            if not head:
                self.wfile.write(data[start:end+1])
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    server.server_close()
    thread.join()


def test_headers_ranges_and_hls_resources(origin):
    proxy = MediaProxy()
    try:
        url = proxy.url_for(origin + '/video.mp4', {'X-Media-Token': 'test-token'})
        response = httpx.get(url, headers={'Range':'bytes=0-31'})
        assert response.status_code == 206
        assert len(response.content) == 32
        assert response.headers['Content-Range'].startswith('bytes 0-31/')
        assert httpx.head(url).headers['Content-Length']
        playlist = httpx.get(proxy.url_for(origin + '/list.m3u8', {'X-Media-Token': 'test-token'})).text
        assert 'clip.ts' not in playlist and 'key.bin' not in playlist
        segment = playlist.splitlines()[-1]
        assert httpx.get(segment).status_code == 200
        assert httpx.get(url.rsplit('/', 1)[0] + '/unregistered').status_code == 404
    finally:
        proxy.close()


@pytest.mark.parametrize('resource', ['/video.mp4', '/stream.m3u8'])
def test_header_protected_playback_seeking_and_audio(qtbot, tmp_path, origin, resource):
    if resource.endswith('m3u8') and not (Path(__file__).parents[1] / 'artifacts/stream.m3u8').exists():
        pytest.skip('Generate H.264 HLS format fixture first')
    from llplayer.app import Window
    from llplayer.core import Settings
    window = Window(Settings(tmp_path / 'settings.json'))
    qtbot.addWidget(window)
    window.show()
    source = services.ResolvedURL(origin + resource, headers={'X-Media-Token': 'test-token'})
    try:
        window.open_media(source)
        qtbot.waitUntil(lambda: window.player.position() > 300, timeout=10000)
        window.player.pause()
        window.player.setPosition(2000)
        qtbot.waitUntil(lambda: window.player.position() >= 1900, timeout=5000)
        assert window.media_path == str(source)
        output = tmp_path / 'chunk.wav'
        services.audio_chunk(window.source, 1, 1, output)
        assert output.stat().st_size > 32000
    finally:
        window.close()
