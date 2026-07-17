"""Read/write the system master volume via pycaw (Windows).

Modern versions of pycaw expose `AudioDevice.EndpointVolume` directly,
without needing the manual `Activate(IAudioEndpointVolume._iid_, ...)`
dance. We try the new API first and fall back to the old one for older
pycaw releases.
"""

from pycaw.pycaw import AudioUtilities

from TextToSpeech.Fast_DF_TTS import speak


def _volume_control():
    """Return an IAudioEndpointVolume interface or raise."""
    speakers = AudioUtilities.GetSpeakers()

    # New pycaw (>=2024): EndpointVolume is a direct attribute.
    endpoint = getattr(speakers, "EndpointVolume", None)
    if endpoint is not None:
        return endpoint

    # Older pycaw: Activate via COM iid.
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume
    interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def get_volume_windows() -> int:
    """Speak the current master volume percentage."""
    try:
        volume = _volume_control()
        current = volume.GetMasterVolumeLevelScalar() * 100
        pct = int(round(current, 2))
        speak(f"the device is running on {pct} percent volume level")
        return pct
    except Exception as exc:  # noqa: BLE001
        speak(f"Could not read system volume: {exc}")
        return -1


def set_volume_windows(percentage: int) -> None:
    """Set the system master volume to `percentage` (0..100)."""
    try:
        if not 0 <= percentage <= 100:
            speak("Volume must be between 0 and 100.")
            return
        volume = _volume_control()
        volume.SetMasterVolumeLevelScalar(percentage / 100.0, None)
        speak(f"Volume set to {percentage} percent")
    except Exception as exc:  # noqa: BLE001
        speak(f"Could not set system volume: {exc}")