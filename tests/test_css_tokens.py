import re

from ferret.web.templating import STATIC_DIR

# token: (light, dark), copied from design/ux.md -> Colours
EXPECTED = {
    "ink": ("#1C2430", "#ECE6DC"),
    "ink-muted": ("#5B6472", "#A9B0BB"),
    "paper": ("#FAF7F2", "#14181F"),
    "surface": ("#FFFFFF", "#1E242D"),
    "line": ("#E6E0D6", "#343B46"),
    "line-soft": ("#F0EBE3", "#2A3039"),
    "field-line": ("#CFC6B8", "#4A525E"),
    "btn-line": ("#D6CEC1", "#4A525E"),
    "amber": ("#C9772F", "#D98A45"),
    "amber-strong": ("#9A4F14", "#F0A866"),
    "accent-fill": ("#9A4F14", "#E39A5B"),
    "on-accent": ("#FFFFFF", "#14181F"),
    "amber-tint": ("#FBEBD9", "#3A2A1C"),
    "amber-ink": ("#7A3D0E", "#F6C08E"),
    "amber-track": ("#F3E6D6", "#2E2A26"),
    "amber-past": ("#EAD9C4", "#4A3D30"),
    "amber-edge": ("#E8C9A6", "#6A4A2C"),
    "ok": ("#1F7A5A", "#5CC79C"),
    "ok-tint": ("#E3F2EB", "#173328"),
    "warn": ("#8A5A00", "#E8B44C"),
    "warn-tint": ("#FFF3D6", "#3A2E12"),
    "danger": ("#B42318", "#F38A80"),
    "danger-tint": ("#FDE8E6", "#3D1C1A"),
    "danger-fill": ("#B42318", "#E0655A"),
    "danger-wash": ("#FFF8F7", "#2A1B1A"),
    "danger-edge": ("#F4C2BD", "#6B2C27"),
    "neutral-tint": ("#EFEBE4", "#2C333D"),
    "backdrop": ("rgba(28,36,48,.45)", "rgba(0,0,0,.6)"),
    "shadow": ("rgba(28,36,48,.25)", "rgba(0,0,0,.5)"),
}

MARKER = "/* end tokens */"
CSS = (STATIC_DIR / "css" / "ferret.css").read_text()


def split_css() -> tuple[str, str]:
    assert CSS.count(MARKER) == 1
    tokens_part, rest = CSS.split(MARKER)
    return tokens_part, rest


def light_block() -> str:
    match = re.search(r":root\s*\{(.*?)\}", split_css()[0], re.DOTALL)
    assert match
    return match.group(1)


def dark_block() -> str:
    pattern = r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{(.*?)\}"
    match = re.search(pattern, split_css()[0], re.DOTALL)
    assert match
    return match.group(1)


def parse(block: str) -> dict[str, str]:
    return {
        name: re.sub(r"\s+", "", value).lower()
        for name, value in re.findall(r"--([a-z-]+):\s*([^;]+);", block)
    }


def test_expected_covers_all_29_tokens():
    assert len(EXPECTED) == 29


def test_light_tokens_match_ux():
    found = parse(light_block())
    for name, (light, _) in EXPECTED.items():
        assert found.get(name) == re.sub(r"\s+", "", light).lower(), name


def test_dark_tokens_match_ux():
    found = parse(dark_block())
    for name, (_, dark) in EXPECTED.items():
        assert found.get(name) == re.sub(r"\s+", "", dark).lower(), name


def test_color_scheme_declared():
    assert "color-scheme: light dark" in light_block()


def test_no_raw_colours_outside_tokens():
    rest = split_css()[1]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", rest)
    assert not re.search(r"\b(rgb|rgba|hsl|hsla)\(", rest)


def test_no_id_selectors():
    assert not re.search(r"(^|[\s,}])#[A-Za-z_-]", split_css()[1], re.MULTILINE)
