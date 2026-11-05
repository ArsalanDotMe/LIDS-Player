"""Playback tools built on Qt and the independently licensed FFmpeg utility."""
from pathlib import Path
import subprocess
import tempfile
from PySide6.QtCore import QObject, QTimer, Qt, QUrl
from PySide6.QtMultimedia import QMediaPlayer
from .services import ffmpeg


class PlaybackTools(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.audio_player = QMediaPlayer(self)
        self.audio_delay = 0
        self.external_audio = ""
        self.reverse = False
        self.recording = None
        self.record_log = None
        self.reverse_timer = QTimer(self)
        self.reverse_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.reverse_timer.setInterval(40)
        self.reverse_timer.timeout.connect(self.reverse_step)
        self.audio_start = QTimer(self)
        self.audio_start.setSingleShot(True)
        self.audio_start.setTimerType(Qt.TimerType.PreciseTimer)
        self.audio_start.timeout.connect(self.start_delayed_audio)
        window.player.positionChanged.connect(self.sync_audio)
        window.player.playbackStateChanged.connect(lambda _state: self.sync_audio(window.player.position()))
        window.player.sourceChanged.connect(self.new_source)
        window.player.mediaStatusChanged.connect(lambda _status: self.sync_audio(window.player.position()))
        window.player.playbackRateChanged.connect(self.audio_player.setPlaybackRate)
        self.audio_player.mediaStatusChanged.connect(lambda _status: self.sync_audio(window.player.position()))
        self.audio_player.tracksChanged.connect(window.refresh_audio)

    def new_source(self, source):
        if getattr(self.window, '_closing', False):
            return
        self.reverse = False
        self.reverse_timer.stop()
        if self.recording:
            self.stop_recording()
        if self.audio_delay or self.external_audio:
            self.audio_player.setSource((QUrl(self.external_audio) if self.external_audio.startswith(("http://", "https://")) else QUrl.fromLocalFile(str(Path(self.external_audio).resolve()))) if self.external_audio else source)

    def set_audio_delay(self, milliseconds):
        self.audio_delay = milliseconds
        self.audio_start.stop()
        if milliseconds or self.external_audio:
            self.window.player.setAudioOutput(None)
            self.audio_player.setAudioOutput(self.window.audio)
            source = (QUrl(self.external_audio) if self.external_audio.startswith(("http://", "https://")) else QUrl.fromLocalFile(str(Path(self.external_audio).resolve()))) if self.external_audio else self.window.player.source()
            if self.audio_player.source() != source:
                self.audio_player.setSource(source)
            self.audio_player.setPlaybackRate(self.window.player.playbackRate())
            self.sync_audio(self.window.player.position())
        else:
            self.audio_player.stop()
            self.audio_player.setAudioOutput(None)
            self.window.player.setAudioOutput(self.window.audio)

    def start_delayed_audio(self):
        if (self.audio_delay or self.external_audio) and self.window.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.audio_player.play()

    def sync_audio(self, position):
        if not self.audio_delay and not self.external_audio:
            return
        player = self.window.player
        target = position - self.audio_delay
        playing = player.playbackState() == QMediaPlayer.PlaybackState.PlayingState and player.mediaStatus() not in (QMediaPlayer.MediaStatus.StalledMedia, QMediaPlayer.MediaStatus.LoadingMedia)
        if not playing or target < 0:
            self.audio_player.pause()
            if playing:
                self.audio_start.start(max(1, -target))
            else:
                self.audio_start.stop()
            if target < 0:
                self.audio_player.setPosition(0)
            return
        self.audio_start.stop()
        if abs(self.audio_player.position() - target) > 160:
            self.audio_player.setPosition(target)
        if not self.external_audio and self.audio_player.activeAudioTrack() != player.activeAudioTrack():
            self.audio_player.setActiveAudioTrack(player.activeAudioTrack())
        if self.audio_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self.audio_player.play()

    def toggle_reverse(self):
        self.reverse = not self.reverse
        self.window.player.pause()
        if self.reverse:
            self.reverse_timer.start()
            self.window.show_play_state(True)
        else:
            self.reverse_timer.stop()
            self.window.show_play_state(False)

    def reverse_step(self):
        player = self.window.player
        if player.position() <= 0:
            self.reverse_timer.stop()
            self.window.show_play_state(False)
            return
        player.setPosition(max(0, player.position() - round(40 * player.playbackRate())))

    def start_recording(self, path):
        if not self.window.source:
            raise ValueError('Open media before recording')
        self.record_log = tempfile.TemporaryFile()
        input_options = ['-ss', str(self.window.player.position() / 1000), '-i', str(self.window.source)]
        if self.external_audio:
            input_options += ['-ss', str(self.window.player.position() / 1000), '-i', self.external_audio]
        maps = ['-map', '0:v?', '-map', '1:a?' if self.external_audio else '0:a?']
        self.recording = subprocess.Popen([ffmpeg(), '-loglevel', 'error', '-y', '-re',
            *input_options, *maps, '-c', 'copy', str(path)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.record_log)
        self.window.statusBar().showMessage('Recording. Use Record again to finish.')

    def stop_recording(self):
        process = self.recording
        if process is None:
            return
        try:
            if process.poll() is None:
                process.communicate(input=b'q\n', timeout=5)
            if process.returncode:
                self.record_log.seek(0)
                raise RuntimeError(self.record_log.read().decode(errors='replace')[-1200:])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdin:
                process.stdin.close()
            self.record_log.close()
            self.recording = None
        self.window.statusBar().showMessage('Recording saved')

    def close(self):
        self.reverse_timer.stop()
        self.audio_start.stop()
        self.audio_player.stop()
        self.audio_player.setSource(QUrl())
        self.audio_player.setAudioOutput(None)
        if self.recording:
            self.stop_recording()
