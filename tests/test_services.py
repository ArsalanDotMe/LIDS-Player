import functools
import http.server
import threading
from pathlib import Path
import httpx
import pytest
from llplayer.core import DEFAULTS
from llplayer.services import Translator, resolve_url, OpenSubtitles


@pytest.mark.parametrize('provider,result', [
    ('Google', [[['Bonjour', 'Hello']]]),
    ('Bing', [{'translations': [{'text': 'Bonjour'}]}]),
    ('Azure', [{'translations': [{'text': 'Bonjour'}]}]),
    ('DeepL', {'translations': [{'text': 'Bonjour'}]}),
    ('DeepLX', {'data': 'Bonjour'}),
    ('Ollama', {'message': {'content': 'Bonjour'}}),
    ('OpenAI', {'choices': [{'message': {'content': 'Bonjour'}}]}),
    ('LM Studio', {'choices': [{'message': {'content': 'Bonjour'}}]}),
    ('KoboldCpp', {'choices': [{'message': {'content': 'Bonjour'}}]}),
    ('Claude', {'choices': [{'message': {'content': 'Bonjour'}}]}),
    ('LiteLLM', {'choices': [{'message': {'content': 'Bonjour'}}]}),
])
def test_translation_contract_and_cache(monkeypatch, provider, result):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith('/auth'):
            return httpx.Response(200, text='example-token')
        return httpx.Response(200, json=result)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr('llplayer.services.httpx.Client', lambda **kwargs: client)
    translator = Translator(dict(DEFAULTS, provider=provider, target='fr', api_key='example', endpoint='http://localhost:1234/v1'))
    assert translator.translate('Hello', ['Earlier line']) == 'Bonjour'
    count = len(requests)
    assert translator.translate('Hello', ['Earlier line']) == 'Bonjour'
    assert len(requests) == count
    if provider in ('OpenAI', 'LM Studio', 'KoboldCpp', 'Claude', 'LiteLLM', 'Ollama'):
        assert b'Earlier line' in requests[-1].content


def test_provider_failure_is_not_cached(monkeypatch):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401)))
    monkeypatch.setattr('llplayer.services.httpx.Client', lambda **kwargs: client)
    translator = Translator(dict(DEFAULTS))
    with pytest.raises(httpx.HTTPStatusError):
        translator.translate('Hello')
    assert not translator.cache


def test_url_resolution_over_http():
    folder = Path(__file__).parent.parent / 'artifacts'
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(folder)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}/test-video.mp4'
        result, title = resolve_url(url)
        assert result == url
        assert title
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_model_download_failure_removes_partial_file(monkeypatch, tmp_path):
    from contextlib import contextmanager
    from llplayer.services import download_model
    @contextmanager
    def stream(*args, **kwargs):
        response = httpx.Response(503, request=httpx.Request('GET', args[1]))
        yield response
    monkeypatch.setattr('llplayer.services.httpx.stream', stream)
    with pytest.raises(httpx.HTTPStatusError):
        download_model('whisper.cpp', 'tiny', tmp_path)
    assert not list(tmp_path.iterdir())


def test_model_download_rejects_unknown_names(tmp_path):
    from llplayer.services import download_model
    with pytest.raises(ValueError):
        download_model('whisper.cpp', '../other-file', tmp_path)
    assert not list(tmp_path.iterdir())
