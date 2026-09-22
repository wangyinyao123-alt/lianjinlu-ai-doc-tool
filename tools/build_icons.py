"""Build crisp platform icon assets from the pixel-art furnace PNG."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


ICON_SIZES = (16, 32, 64, 128, 256, 512, 1024)


def resized(source: Image.Image, size: int) -> Image.Image:
    return source.resize((size, size), Image.Resampling.NEAREST)


def build(source_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    source = Image.open(source_path).convert("RGBA")

    ico_path = output_dir / "alchemy-furnace.ico"
    source.save(ico_path, format="ICO", sizes=[(size, size) for size in ICON_SIZES if size <= 256])

    icns_path = output_dir / "alchemy-furnace.icns"
    source_128 = resized(source, 128)
    source_256 = resized(source, 256)
    source_512 = resized(source, 512)
    source_1024 = resized(source, 1024)
    source_128.save(icns_path, format="ICNS", append_images=[source_256, source_512, source_1024])

    iconset = output_dir / "alchemy-furnace.iconset"
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        resized(source, size).save(iconset / f"icon_{size}x{size}.png")
        resized(source, size * 2).save(iconset / f"icon_{size}x{size}@2x.png")

    # Keep a platform-neutral PNG beside the generated formats for portable
    # launchers and package manifests.
    resized(source, 1024).save(output_dir / "alchemy-furnace-1024.png")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.source, args.output)


if __name__ == "__main__":
    main()
