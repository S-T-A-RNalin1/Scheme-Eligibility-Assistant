"""Make the logo's flat background transparent so it sits on any slide colour."""
from pathlib import Path

import numpy as np
from PIL import Image

IMG = Path(__file__).absolute().parent / "img"
im = np.asarray(Image.open(IMG / "muj_logo.png").convert("RGB")).astype(float)
bgs = np.array([[228, 194, 182], [255, 252, 249]], dtype=float)  # pink-beige band + white corner
# Distance to the colour segment between the two background tones (covers their blended diagonal edge).
a, b = bgs
t = np.clip(((im - a) @ (b - a)) / ((b - a) @ (b - a)), 0, 1)
nearest = a + t[..., None] * (b - a)
dist = np.linalg.norm(im - nearest, axis=-1)
alpha = np.clip((dist - 12) / 80, 0, 1)
# Un-blend anti-aliased edges: p = a*fg + (1-a)*bg  ->  fg = (p - (1-a)*bg) / a
fg = np.where(alpha[..., None] > 0, (im - (1 - alpha[..., None]) * nearest) / np.maximum(alpha[..., None], 1e-3), 0)
rgba = np.dstack([np.clip(fg, 0, 255), alpha * 255]).astype(np.uint8)
out = Image.fromarray(rgba, "RGBA")
out = out.crop(out.getbbox())
big = out.resize((out.width * 4, out.height * 4), Image.LANCZOS)
big.save(IMG / "muj_logo_transparent.png")
print(out.size, "->", big.size)
