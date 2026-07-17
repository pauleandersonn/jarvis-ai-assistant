"""Compatibility shim package exposing a minimal `pyaudio` API on top of `sounddevice`.

Why this exists: `pyaudio` does not have a pre-built wheel for Python
3.14 yet and needs Visual Studio Build Tools to compile. `sounddevice`
ships with a wheel and works on Py 3.14 out of the box. We drop a
package directory called `pyaudio` into the project so that
`import pyaudio` resolves to this shim without any extra PYTHONPATH
trickery.

We deliberately avoid numpy: on Python 3.14, numpy raises
`ImportError: cannot load module more than once per process` if it is
imported inside an import hook. Built-in `array` is enough to convert
float32 samples to int16 PCM bytes.
"""

import array

import sounddevice as sd

# pyaudio constants used by this project
paInt16 = 16
FORMAT = 16  # alias used in some files


def _default_input_device():
    try:
        return sd.default.device[0]
    except Exception:
        return None


class Stream:
    """Mimics the parts of `pyaudio.Stream` that the project actually uses."""

    def __init__(self, sd_input_stream, rate, channels, frames_per_buffer):
        self._stream = sd_input_stream
        self._rate = rate
        self._channels = channels
        self._frames_per_buffer = frames_per_buffer
        self._closed = False

    def read(self, num_frames, exception_on_overflow=False):
        try:
            data, _overflowed = self._stream.read(num_frames)
        except Exception as exc:
            if exception_on_overflow:
                raise
            return b""

        # `data` is a 2D numpy ndarray: shape (num_frames, channels).
        # Clip float32 in [-1, 1] -> int16 PCM using the built-in `array` module.
        samples = array.array("h")
        # Flatten manually to avoid numpy being loaded inside this module.
        try:
            flat = data.reshape(-1)
        except AttributeError:
            rows = data if isinstance(data, (list, tuple)) else [data]
            flat = []
            for chunk in rows:
                inner = chunk if isinstance(chunk, (list, tuple)) else [chunk]
                flat.extend(inner)

        for sample in flat:
            val = int(sample * 32767)
            if val > 32767:
                val = 32767
            elif val < -32768:
                val = -32768
            samples.append(val)
        return samples.tobytes()

    def stop_stream(self):
        try:
            self._stream.stop()
        except Exception:
            pass

    def close(self):
        if self._closed:
            return
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass
        self._closed = True

    def is_active(self):
        try:
            return bool(self._stream.active)
        except Exception:
            return False

    def get_input_latency(self):
        try:
            return float(self._stream.latency)
        except Exception:
            return 0.0

    def get_samplerate(self):
        return self._rate


class PyAudio:
    """Drop-in replacement for the subset of `pyaudio.PyAudio` used here."""

    def __init__(self):
        self._default_input = _default_input_device()

    def get_device_count(self):
        try:
            return len(sd.query_devices())
        except Exception:
            return 0

    def get_default_input_device_info(self):
        try:
            return sd.query_devices(kind="input")
        except Exception:
            return {"name": "default", "index": 0, "maxInputChannels": 1}

    def open(self, format=None, rate=16000, channels=1, input=True,
             frames_per_buffer=1024, start=True, input_device_index=None):
        if not input:
            raise NotImplementedError("Output stream not implemented in shim.")

        device = (
            input_device_index
            if input_device_index is not None
            else self._default_input
        )
        try:
            sd_stream = sd.InputStream(
                samplerate=rate,
                channels=channels,
                dtype="float32",
                blocksize=frames_per_buffer,
                device=device,
            )
            if start:
                sd_stream.start()
            return Stream(sd_stream, rate, channels, frames_per_buffer)
        except Exception as exc:
            raise RuntimeError(f"Could not open audio input: {exc}") from exc

    def terminate(self):
        # sounddevice manages its own portaudio lifecycle.
        return None


def get_sample_size(fmt: int) -> int:
    """pyaudio-style helper: bytes per sample for a given format."""
    if fmt in (paInt16, 16):
        return 2
    if fmt == 8:
        return 1
    return 2