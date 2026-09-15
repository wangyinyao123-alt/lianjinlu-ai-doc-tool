#!/usr/bin/env python3
"""Create photo-derived editorial diptychs next to their source photographs.

The source photo is kept as the principal image. The lower section follows the
photo-abstract-editorial skill: a flat ivory panel, a sparse photo-derived
abstract motif, and one restrained title.
"""

from __future__ import annotations

import colorsys
import hashlib
import math
import random
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps


ROOT = Path(__file__).resolve().parents[1]
PHOTO_DIR = ROOT / "照片素材"
CANVAS_WIDTH = 1200
PANEL_RATIO = 0.55
IVORY = (243, 240, 232)

# Titles are grounded in the visible spatial facts of each photograph.
TITLES = {
    "HQJ22WvbEAA9pwV": "Red Gate Horizon",
    "HQKTmlqbcAA5YJn": "Seaside Wires",
    "HQMHFC-XQAAdlWq": "Green Roadway",
    "HQO_HJ0bcAAKpsA": "Island Tide",
    "HQO_J5QbgAAd8xG": "Long Water Crossing",
    "HQO_zIMaMAAuP9t": "Night Towerline",
    "HQO_zNPaIAAaxHm": "Amber Vertical",
    "HQO_zOTbgAASiC_": "Blue Hour Tower",
    "IMG_3509": "Spring Geometry",
    "IMG_3515": "Soft Canopy",
    "IMG_3516": "Glass Garden",
    "IMG_3523": "Surface Study",
    "IMG_3544": "Still Current",
    "IMG_3553": "Measured Bloom",
    "IMG_3562": "Quiet Current",
    "IMG_3581": "Pink Facade",
    "IMG_3583": "Branching Light",
    "IMG_3612": "Blossom Interval",
    "IMG_3619": "Curved Facade",
}


def title_font(size: int):
    candidates = (
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/Library/Fonts/Georgia.ttf",
        "/System/Library/Fonts/Times.ttc",
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            try:
                from PIL import ImageFont

                return ImageFont.truetype(str(path), size)
            except OSError:
                pass
    from PIL import ImageFont

    return ImageFont.load_default()


def stable_rng(stem: str) -> random.Random:
    seed = int(hashlib.sha256(stem.encode("utf-8")).hexdigest()[:16], 16)
    return random.Random(seed)


def muted(rgb: tuple[int, int, int], amount: float = 0.68) -> tuple[int, int, int]:
    """Keep the source hue while lowering saturation for the panel."""
    r, g, b = [channel / 255 for channel in rgb]
    h, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    saturation *= amount
    lightness = 0.5 + (lightness - 0.5) * 0.82
    rr, gg, bb = colorsys.hls_to_rgb(h, lightness, saturation)
    return tuple(round(channel * 255) for channel in (rr, gg, bb))


def palette_from(photo: Image.Image, count: int = 5) -> list[tuple[int, int, int]]:
    sample = photo.resize((80, 60), Image.Resampling.BILINEAR).convert("RGB")
    quantized = sample.quantize(colors=12, method=Image.Quantize.MEDIANCUT).convert("RGB")
    counts = Counter(quantized.getdata())
    selected: list[tuple[int, int, int]] = []
    for color, occurrences in counts.most_common():
        # Skip tiny compression artifacts and colors indistinguishable from an
        # already selected role. The source remains the only color authority.
        if occurrences < 18:
            continue
        if all(sum((color[index] - other[index]) ** 2 for index in range(3)) > 900 for other in selected):
            selected.append(muted(color))
        if len(selected) == count:
            break
    if not selected:
        selected = [(70, 84, 90), (123, 145, 134), (188, 155, 145)]
    return selected


def normalized_regions(photo: Image.Image, palette_count: int = 6):
    """Return coarse color regions and a small edge map for selective memory."""
    width, height = 64, 48
    sample = photo.resize((width, height), Image.Resampling.BILINEAR).convert("RGB")
    quantized = sample.quantize(colors=palette_count, method=Image.Quantize.MEDIANCUT).convert("RGB")
    counts = Counter(quantized.getdata())
    ordered = [color for color, _ in counts.most_common()]
    regions = []
    for color in ordered[:5]:
        coords = [(x, y) for y in range(height) for x in range(width) if quantized.getpixel((x, y)) == color]
        if len(coords) < 20:
            continue
        xs = [x for x, _ in coords]
        ys = [y for _, y in coords]
        regions.append(
            {
                "color": muted(color),
                "count": len(coords),
                "cx": sum(xs) / (len(xs) * (width - 1)),
                "cy": sum(ys) / (len(ys) * (height - 1)),
                "sx": max(0.06, (max(xs) - min(xs)) / (width - 1)),
                "sy": max(0.06, (max(ys) - min(ys)) / (height - 1)),
            }
        )
    gray = ImageOps.grayscale(sample)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_values = edges.load()
    row_scores = [sum(edge_values[x, y] for x in range(width)) / width for y in range(height)]
    column_scores = [sum(edge_values[x, y] for y in range(height)) / height for x in range(width)]
    return regions, row_scores, column_scores


def choose_positions(values: list[float], limit: int, minimum_gap: int) -> list[int]:
    ranked = sorted(range(len(values)), key=lambda index: values[index], reverse=True)
    chosen: list[int] = []
    for index in ranked:
        if all(abs(index - other) >= minimum_gap for other in chosen):
            chosen.append(index)
        if len(chosen) == limit:
            break
    return sorted(chosen)


def irregular_field(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], color, rng: random.Random, alpha: int):
    """Draw a sparse, slightly irregular planar mass; no texture or shading."""
    left, top, right, bottom = box
    cx = (left + right) / 2
    cy = (top + bottom) / 2
    rx = (right - left) / 2
    ry = (bottom - top) / 2
    points = []
    for index in range(12):
        angle = math.tau * index / 12
        variation = 0.88 + rng.uniform(-0.08, 0.08)
        points.append((cx + math.cos(angle) * rx * variation, cy + math.sin(angle) * ry * variation))
    draw.polygon(points, fill=(*color, alpha))


def draw_abstract_panel(photo: Image.Image, title: str, stem: str, panel_height: int) -> Image.Image:
    panel = Image.new("RGB", (CANVAS_WIDTH, panel_height), IVORY)
    draw = ImageDraw.Draw(panel, "RGBA")
    rng = stable_rng(stem)
    regions, row_scores, column_scores = normalized_regions(photo)
    colors = palette_from(photo)

    # Keep the motif compact so whitespace remains the dominant visual fact.
    motif_left = CANVAS_WIDTH * 0.18
    motif_width = CANVAS_WIDTH * 0.64
    motif_top = panel_height * 0.10
    motif_height = panel_height * 0.34

    # Primary mark family: overlapping flat fields whose positions and scale
    # follow coarse color mass in the source photo.
    for index, region in enumerate(regions[:4]):
        cx = motif_left + region["cx"] * motif_width
        cy = motif_top + region["cy"] * motif_height
        width = max(92, min(motif_width * 0.62, motif_width * (0.16 + region["sx"] * 0.76)))
        height = max(26, min(motif_height * 0.72, motif_height * (0.18 + region["sy"] * 0.62)))
        # Small deterministic offsets keep the marks observed and asymmetric.
        cx += (index - 1.5) * 5 + rng.uniform(-9, 9)
        cy += rng.uniform(-6, 6)
        irregular_field(
            draw,
            (cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2),
            region["color"],
            rng,
            145 if index else 165,
        )

    # Supporting family 1: a few source-derived axes. The stronger orientation
    # (horizontal or vertical) gets priority, preserving scene direction.
    horizontal = sum(row_scores) >= sum(column_scores)
    dark = min(colors, key=lambda color: sum(color))
    if horizontal:
        for row in choose_positions(row_scores, 3, 7):
            y = motif_top + row / 47 * motif_height
            start = motif_left + (0.10 + 0.05 * (row % 3)) * motif_width
            end = motif_left + (0.77 + 0.04 * (row % 2)) * motif_width
            draw.line((start, y, end, y + (row % 2) * 4), fill=(*dark, 142), width=2)
    else:
        for column in choose_positions(column_scores, 3, 8):
            x = motif_left + column / 63 * motif_width
            y1 = motif_top + 0.06 * motif_height
            y2 = motif_top + 0.84 * motif_height
            draw.line((x, y1, x + (column % 2) * 4, y2), fill=(*dark, 142), width=2)

    # Supporting family 2: only a few points at strong local edge positions,
    # echoing repeated lights, blossoms, people, or other visible intervals.
    candidates = []
    for y in range(2, 46, 3):
        for x in range(2, 62, 4):
            strength = row_scores[y] + column_scores[x]
            candidates.append((strength, x, y))
    points = []
    for _, x, y in sorted(candidates, reverse=True):
        if all(abs(x - px) > 8 or abs(y - py) > 6 for px, py in points):
            points.append((x, y))
        if len(points) == 4:
            break
    accent = colors[-1] if len(colors) > 1 else dark
    for index, (x, y) in enumerate(points):
        px = motif_left + x / 63 * motif_width
        py = motif_top + y / 47 * motif_height
        radius = 3 + (index % 2)
        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=(*accent, 180))

    # One title only; no labels, dates, captions, logos, or watermarks.
    draw.text(
        (CANVAS_WIDTH * 0.075, panel_height * 0.82),
        title,
        fill=(*dark, 225),
        font=title_font(max(24, round(CANVAS_WIDTH * 0.025))),
    )
    return panel


def build_card(source: Path, output: Path) -> None:
    with Image.open(source) as raw:
        source_image = ImageOps.exif_transpose(raw).convert("RGB")
        photo_height = round(CANVAS_WIDTH * source_image.height / source_image.width)
        photo = source_image.resize((CANVAS_WIDTH, photo_height), Image.Resampling.LANCZOS)
        panel_height = round(CANVAS_WIDTH * PANEL_RATIO)
        panel = draw_abstract_panel(photo, TITLES.get(source.stem, "Quiet Structure"), source.stem, panel_height)
        canvas = Image.new("RGB", (CANVAS_WIDTH, photo_height + panel_height), IVORY)
        canvas.paste(photo, (0, 0))
        canvas.paste(panel, (0, photo_height))
        canvas.save(output, format="JPEG", quality=94, optimize=True, progressive=True)


def main() -> None:
    sources = sorted(
        source
        for source in PHOTO_DIR.iterdir()
        if source.is_file()
        and source.suffix.lower() in {".jpg", ".jpeg", ".png"}
        and not source.name.endswith("-abstract.jpg")
    )
    for source in sources:
        output = PHOTO_DIR / f"{source.stem}-abstract.jpg"
        build_card(source, output)
        print(output)


if __name__ == "__main__":
    main()
