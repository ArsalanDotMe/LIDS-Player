"""Optional live checks. Downloads the tiny model and calls public translation.

Use --online to check the original public TED demo. Supply both whisper.cpp
arguments to exercise a locally installed second engine. No paid API keys needed.
"""
import argparse
import io
import json
from pathlib import Path
import sys
from PIL import Image, ImageDraw, ImageFont
from llplayer.core import DEFAULTS
from llplayer.services import Translator, transcribe_chunk, ocr_image, resolve_url, audio_chunk

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--online', action='store_true')
parser.add_argument('--speech', type=Path, help='Your own speech recording to test ASR')
parser.add_argument('--whisper-cli')
parser.add_argument('--whisper-model')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
settings = dict(DEFAULTS, source='en', target='fr')
results = {}

def check(name, function):
    try:
        results[name] = function()
    except Exception as error:
        # Do not record signed media URLs or credentials from provider errors.
        results[name + '_error'] = type(error).__name__

speech = args.speech
check('translation', lambda: Translator(settings).translate('Welcome to the language lesson.'))
if speech:
    check('asr', lambda: [c.__dict__ for c in transcribe_chunk(str(speech), 0, 15, settings)])
else:
    results['asr_status'] = 'Not checked: supply --speech with your own recording.'

def recognize():
    image = Image.new('RGB', (800, 100), 'black')
    ImageDraw.Draw(image).text((15, 20), 'Welcome to LLPlayer', fill='white', font=ImageFont.load_default(size=40))
    out = io.BytesIO()
    image.save(out, format='PNG')
    return ocr_image(out.getvalue())

check('ocr', recognize)
if speech and args.whisper_cli and args.whisper_model:
    cpp = dict(settings, asr_engine='whisper.cpp', whisper_cli=args.whisper_cli, whisper_model=args.whisper_model)
    check('whisper_cpp', lambda: [c.__dict__ for c in transcribe_chunk(str(speech), 0, 15, cpp)])
if args.online:
    def online():
        url, title = resolve_url('https://www.ted.com/talks/linus_torvalds_the_mind_behind_linux')
        audio_chunk(url, 0, 2, str(root / 'artifacts/online-audio.wav'))
        return {'resolved': True, 'title': title}
    check('online', online)
(root / 'artifacts').mkdir(exist_ok=True)
(root / 'artifacts/live-services.json').write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
sys.exit(1 if any(key.endswith('_error') for key in results) else 0)
