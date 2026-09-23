"""Create two disposable local PNGs for the Messaging size checks."""

import os
import tempfile
from pathlib import Path

from PIL import Image


folder = Path(tempfile.gettempdir()) / "moveon-messaging-ui-test"
folder.mkdir(exist_ok=True)

for name, edge in (("valid-7mb.png", 1500), ("over-10mb.png", 2100)):
    path = folder / name
    if not path.exists():
        image = Image.frombytes("RGB", (edge, edge), os.urandom(edge * edge * 3))
        image.save(path, format="PNG")
    print(f"{path} ({path.stat().st_size / 1024 / 1024:.1f} MiB)")
