import os
import base64
from io import BytesIO
from PIL import Image, ImageTk, ImageDraw
from config import ICON_DATA

def load_icons(placeholder):
    """
    Laddar ikoner från disk, base64 eller skapar enkla fallback-ikoner.
    """
    names = ("open", "zoom_in", "zoom_out", "rotate", "search", "up", "down")
    icons = {}
    app_dir = os.path.dirname(os.path.abspath(__file__))
    icons_dir = os.path.join(app_dir, "icons")

    for name in names:
        icon_img = None

        # 1) Försök läsa från disk
        path = os.path.join(icons_dir, f"{name}.png")
        if os.path.isfile(path):
            try:
                pil_img = Image.open(path).convert("RGBA")
                icon_img = ImageTk.PhotoImage(pil_img)
            except Exception:
                pass

        # 2) Försök läsa från base64
        if icon_img is None and name in ICON_DATA and ICON_DATA[name]:
            try:
                b64 = ICON_DATA[name]
                if isinstance(b64, (bytes, bytearray)):
                    b64 = b64.decode()
                b64 = "".join(b64.split())
                b64 += "=" * ((4 - len(b64) % 4) % 4)
                decoded = base64.b64decode(b64)
                pil_img = Image.open(BytesIO(decoded)).convert("RGBA")
                icon_img = ImageTk.PhotoImage(pil_img)
            except Exception:
                pass

        # 3) Fallback-ikon (enkel ruta)
        if icon_img is None:
            img = Image.new("RGBA", (18, 18), (200, 200, 200, 255))
            draw = ImageDraw.Draw(img)
            draw.rectangle((2, 2, 16, 16), outline=(100, 100, 100, 255))
            icon_img = ImageTk.PhotoImage(img)

        icons[name] = icon_img

    # säkerställ att alla nycklar finns
    for k in names:
        if k not in icons:
            icons[k] = placeholder

    return icons
