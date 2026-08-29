import math
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

WIDTH, HEIGHT = 1200, 630
img = Image.new("RGBA", (WIDTH, HEIGHT), (9, 13, 22, 255))
draw = ImageDraw.Draw(img)

# 1. Subtle Dark Tech Grid
for x in range(0, WIDTH, 40):
    draw.line([(x, 0), (x, HEIGHT)], fill=(19, 30, 49, 100), width=1)
for y in range(0, HEIGHT, 40):
    draw.line([(0, y), (WIDTH, y)], fill=(19, 30, 49, 100), width=1)

# 2. Glowing Radial Mesh Glow behind Center
glow_center = (WIDTH // 2, 260)
for r in range(220, 0, -10):
    alpha = int(35 * (1 - r / 220))
    draw.ellipse(
        [glow_center[0] - r, glow_center[1] - r, glow_center[0] + r, glow_center[1] + r],
        fill=(20, 184, 166, alpha)
    )

# 3. Central Synapse Neural Nodes
nodes = [
    (WIDTH // 2 - 120, 180),
    (WIDTH // 2 + 120, 180),
    (WIDTH // 2, 290),
    (WIDTH // 2 - 80, 360),
    (WIDTH // 2 + 80, 360)
]
for i in range(len(nodes)):
    for j in range(i + 1, len(nodes)):
        draw.line([nodes[i], nodes[j]], fill=(45, 212, 191, 140), width=2)

for n in nodes:
    draw.ellipse([n[0]-14, n[1]-14, n[0]+14, n[1]+14], fill=(19, 78, 74, 255), outline=(45, 212, 191, 255), width=2)
    draw.ellipse([n[0]-6, n[1]-6, n[0]+6, n[1]+6], fill=(255, 255, 255, 255))

# 4. Text Headlines
def load_font(paths: list[str], size: int):
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


sans_paths = [
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/SFNS.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
mono_paths = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/SFNSMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]
font_title = load_font(sans_paths, 62)
font_sub = load_font(sans_paths, 22)
font_desc = load_font(sans_paths, 24)
font_footer = load_font(mono_paths, 17)


def draw_centered(y: int, text: str, font, fill) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    x = (WIDTH - (box[2] - box[0])) // 2
    draw.text((x, y), text, fill=fill, font=font)


# Badge: a compact statement of the registry's trust rule.
badge_text = "EVIDENCE BEFORE LABELS"
badge_box = draw.textbbox((0, 0), badge_text, font=font_sub)
badge_width = badge_box[2] - badge_box[0] + 48
draw.rounded_rectangle(
    [WIDTH // 2 - badge_width // 2, 70, WIDTH // 2 + badge_width // 2, 112],
    radius=8,
    fill=(19, 78, 74, 220),
    outline=(20, 184, 166, 255),
    width=1,
)
draw_centered(79, badge_text, font_sub, (45, 212, 191, 255))

# Title and honest product scope.
draw_centered(397, "SYNAPSE-MESH", font_title, (255, 255, 255, 255))
draw_centered(
    478,
    "Compatibility evidence for software agents — or an honest miss",
    font_desc,
    (203, 213, 225, 255),
)

# Footer bar
draw.line([(80, 550), (WIDTH - 80, 550)], fill=(30, 41, 59, 255), width=1)
footer_text = "MCP + REST  •  Reproducible scope  •  Data-minimising by design"
draw_centered(572, footer_text, font_footer, (100, 116, 139, 255))

output_path = Path("app/static/og-image.png")
output_path.parent.mkdir(parents=True, exist_ok=True)
img.save(output_path, "PNG")
print(f"Generated OG image at {output_path} ({WIDTH}x{HEIGHT})")
