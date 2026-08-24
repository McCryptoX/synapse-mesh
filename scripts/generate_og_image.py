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
try:
    # Try system fonts or default
    font_title = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 62)
    font_sub = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 26)
    font_desc = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
    font_footer = ImageFont.truetype("/System/Library/Fonts/Monaco.dfont", 18)
except Exception:
    font_title = font_sub = font_desc = font_footer = ImageFont.load_default()

# Badge: CI/CD FOR AI KNOWLEDGE
badge_text = " CI/CD FOR AI KNOWLEDGE "
draw.rounded_rectangle([WIDTH // 2 - 170, 70, WIDTH // 2 + 170, 110], radius=8, fill=(19, 78, 74, 200), outline=(20, 184, 166, 255), width=1)
draw.text((WIDTH // 2 - 150, 78), badge_text, fill=(45, 212, 191, 255), font=font_sub)

# Title: SYNAPSE-MESH
draw.text((WIDTH // 2 - 250, 400), "SYNAPSE", fill=(255, 255, 255, 255), font=font_title)
draw.text((WIDTH // 2 + 75, 400), "-MESH", fill=(20, 184, 166, 255), font=font_title)

# Tagline
desc_text = "Deterministic, Sandbox-Verified Living Solutions for AI Coding Agents"
draw.text((WIDTH // 2 - 340, 480), desc_text, fill=(203, 213, 225, 255), font=font_desc)

# Footer bar
draw.line([(80, 550), (WIDTH - 80, 550)], fill=(30, 41, 59, 255), width=1)
footer_text = "MCP Spec 2026-07-28  •  https://synapsemesh.dev  •  Zero-PII & GDPR Verified"
draw.text((WIDTH // 2 - 350, 570), footer_text, fill=(100, 116, 139, 255), font=font_footer)

output_path = Path("app/static/og-image.png")
output_path.parent.mkdir(parents=True, exist_ok=True)
img.save(output_path, "PNG")
print(f"Generated OG image at {output_path} ({WIDTH}x{HEIGHT})")
