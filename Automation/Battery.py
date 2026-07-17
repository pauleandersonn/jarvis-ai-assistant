# pip install psutil
# CTRL + J Terminal

import psutil
import time
import threading
from TextToSpeech.Fast_DF_TTS import speak
from Alert import Alert


def _get_battery():
    """Return psutil battery object or None on desktops without a battery."""
    try:
        return psutil.sensors_battery()
    except Exception:
        return None


def battery_Alert():
    """Poll battery level every ~13 seconds and announce changes.

    Skips itself silently on desktops (which have no battery).
    """
    battery = _get_battery()
    if battery is None:
        print("[Battery] no battery detected, skipping alert thread.")
        return

    while True:
        time.sleep(3)
        try:
            percentage = int(battery.percent)
        except Exception:
            time.sleep(10)
            continue

        if percentage == 100:
            t1 = threading.Thread(target=Alert, args=("100%charge",))
            t2 = threading.Thread(target=speak, args=("100% charged. Please unplug it.",))
            t1.start(); t2.start(); t1.join(); t2.join()
        elif percentage <= 5:
            t1 = threading.Thread(target=Alert, args=("Battery is going to died",))
            t2 = threading.Thread(target=speak, args=("Sir, sorry to disturb you but this is your last chance sir, charge your system now.",))
            t1.start(); t2.start(); t1.join(); t2.join()
        elif percentage <= 10:
            t1 = threading.Thread(target=Alert, args=("Battery is too Low",))
            t2 = threading.Thread(target=speak, args=("Sir, sorry to disturb you but we are running on very low battery power.",))
            t1.start(); t2.start(); t1.join(); t2.join()
        elif percentage <= 20:
            t1 = threading.Thread(target=Alert, args=("Battery Low",))
            t2 = threading.Thread(target=speak, args=("Sir, sorry to disturb you but battery is Low now.",))
            t1.start(); t2.start(); t1.join(); t2.join()

        time.sleep(10)


def check_plug():
    """Watch for charger plug/unplug transitions.

    Skips itself silently on desktops (which have no battery).
    """
    print("_____started___")
    battery = _get_battery()
    if battery is None:
        print("[Battery] no battery detected, skipping plug watcher.")
        return

    previous_state = battery.power_plugged
    while True:
        try:
            battery = _get_battery()
            if battery is None:
                # Battery was removed during runtime. Stop the loop.
                print("[Battery] battery went away, stopping plug watcher.")
                return

            if battery.power_plugged != previous_state:
                if battery.power_plugged:
                    t1 = threading.Thread(target=Alert, args=("Charging **STARTED**",))
                    t2 = threading.Thread(target=speak, args=("Charging Started",))
                else:
                    t1 = threading.Thread(target=Alert, args=("Charging **STOP**",))
                    t2 = threading.Thread(target=speak, args=("Charging Stop",))
                t1.start(); t2.start(); t1.join(); t2.join()
                previous_state = battery.power_plugged

            time.sleep(1)
        except Exception as exc:
            print(f"[Battery] plug watcher error: {exc}")
            time.sleep(1)


def check_percentage():
    """Speak the current battery percentage once."""
    battery = _get_battery()
    if battery is None:
        return "No battery detected (this looks like a desktop)."
    try:
        percent = int(battery.percent)
    except Exception as exc:
        return f"Could not read battery: {exc}"

    msg = f"The device is running on {percent}% power"
    t1 = threading.Thread(target=Alert, args=(msg,))
    t2 = threading.Thread(target=speak, args=(msg,))
    t1.start(); t2.start(); t1.join(); t2.join()
    return msg