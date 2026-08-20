import re
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


def svg_filename_to_codepoint(filename: str) -> int:
    stem = filename.rsplit(".", 1)[0]
    prefix = stem.split("_", 1)[0]

    if len(prefix) == 1:
        return ord(prefix)

    if re.fullmatch(r"u[0-9a-fA-F]{4,6}", prefix):
        return int(prefix[1:], 16)

    if re.fullmatch(r"[0-9a-fA-F]{4,6}", prefix):
        return int(prefix, 16)

    raise ValueError(f"Cannot infer a Unicode code point from {filename!r}.")


@dataclass(frozen=True)
class FontConfig:
    upm: int = 1000
    advance_width: int = 600
    space_width: int = 250
    fontname: str = "MyCustomFont"
    fullname: str = "My Custom Font"
    familyname: str = "My Family"


def load_config(config_path: str | Path = "config.toml") -> FontConfig:
    path = Path(config_path)
    if not path.exists():
        return FontConfig()

    with path.open("rb") as config_file:
        data = tomllib.load(config_file)

    font_settings = data.get("font", {})
    return FontConfig(
        upm=int(font_settings.get("upm", 1000)),
        advance_width=int(font_settings.get("advance_width", 600)),
        space_width=int(font_settings.get("space_width", 250)),
        fontname=str(font_settings.get("fontname", "MyCustomFont")),
        fullname=str(font_settings.get("fullname", "My Custom Font")),
        familyname=str(font_settings.get("familyname", "My Family")),
    )


CONFIG = load_config()


def vertical_metrics(upm: int) -> tuple[int, int, int]:
    """Return (ascent, descent, line_height) for a given UPM.

    Fixed internal constants, not user knobs: the classic 80/20 em split with
    a 1.2 em default line height — the same proportions as Times/Arial-class
    fonts — so generated fonts drop in next to system fonts without changing
    line spacing.  Apps control actual line spacing at layout time
    (CSS line-height etc.); the font only ships a sane default.
    """
    ascent = round(upm * 0.8)
    descent = upm - ascent
    line_height = round(upm * 1.2)
    return ascent, descent, line_height
