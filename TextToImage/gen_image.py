"""Generate an image from a text prompt.

Originally this module hit a broken endpoint on the original author's machine.
We now use https://pollinations.ai which:
- is free and anonymous (no API key required)
- returns a direct image URL
- works from any HTTP client (no auth headers needed)
"""

import pathlib
import random
import time
import urllib.parse
import urllib.request

OUTPUT_DIR = pathlib.Path(__file__).resolve().parent / "Generated"
OUTPUT_DIR.mkdir(exist_ok=True)


def generate_image(prompt: str) -> str:
    """Generate an image for `prompt` and save it under ./Generated/.

    Returns the local file path of the saved image, or an error message string.
    """
    try:
        # Pollinations: https://image.pollinations.ai/prompt/{prompt}?...
        # Adding a random seed forces a fresh generation each time.
        seed = random.randint(1, 1_000_000)
        encoded_prompt = urllib.parse.quote(prompt)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?seed={seed}&nologo=true"
        )
        filename = OUTPUT_DIR / f"img_{int(time.time())}_{seed}.jpg"

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            filename.write_bytes(resp.read())

        return f"Image generated: {filename}"
    except Exception as exc:  # noqa: BLE001
        return f"Image generation failed: {exc}"