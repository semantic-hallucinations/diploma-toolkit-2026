from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
import math
from pathlib import Path
import textwrap
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont


BLACK = "#000000"
WHITE = "#ffffff"
LIGHT = "#f7f7f7"


@dataclass
class Shape:
    id: str
    kind: str
    x: float
    y: float
    w: float
    h: float
    text: str = ""
    header: str | None = None
    sections: list[list[str]] = field(default_factory=list)
    stereotype: str | None = None
    dashed: bool = False
    fill: str = WHITE
    stroke: str = BLACK
    parent: str | None = None


@dataclass
class Connector:
    id: str
    source: str
    target: str
    label: str = ""
    kind: str = "association"
    dashed: bool = False
    start_label: str = ""
    end_label: str = ""
    start_marker: str = ""
    end_marker: str = ""
    points: list[tuple[float, float]] | None = None
    label_position: tuple[float, float] | None = None


@dataclass
class Canvas:
    profile: str
    title: str
    width: int
    height: int
    shapes: list[Shape] = field(default_factory=list)
    connectors: list[Connector] = field(default_factory=list)

    def shape_map(self) -> dict[str, Shape]:
        return {shape.id: shape for shape in self.shapes}


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/Library/Fonts/Arial Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        )
    candidates.extend(
        [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


FONT = load_font(16)
FONT_SMALL = load_font(13)
FONT_TINY = load_font(11)
FONT_BOLD = load_font(16, bold=True)
FONT_TITLE = load_font(18, bold=True)


def text_bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont = FONT) -> tuple[int, int]:
    if not text:
        return 0, 0
    box = draw.multiline_textbbox((0, 0), text, font=font, spacing=4)
    return int(box[2] - box[0]), int(box[3] - box[1])


def wrap_text(text: str, width_px: float, font: ImageFont.ImageFont = FONT) -> str:
    if not text:
        return ""
    text = text.replace("\\n", "\n")
    avg = max(7, int(font.size * 0.56) if hasattr(font, "size") else 8)
    width_chars = max(8, int(width_px / avg))
    lines: list[str] = []
    for raw in text.splitlines():
        if not raw.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(raw, width=width_chars, break_long_words=False) or [raw])
    return "\n".join(lines)


def fitted_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    width_px: float,
    height_px: float,
    *,
    bold: bool = False,
    start_size: int = 16,
    min_size: int = 10,
) -> tuple[str, ImageFont.ImageFont]:
    for size in range(start_size, min_size - 1, -1):
        font = load_font(size, bold=bold)
        wrapped = wrap_text(text, width_px, font)
        tw, th = text_bbox(draw, wrapped, font)
        if tw <= width_px and th <= height_px:
            return wrapped, font
    font = load_font(min_size, bold=bold)
    return wrap_text(text, width_px, font), font


def center(shape: Shape) -> tuple[float, float]:
    return shape.x + shape.w / 2, shape.y + shape.h / 2


def boundary_point(shape: Shape, toward: tuple[float, float]) -> tuple[float, float]:
    cx, cy = center(shape)
    tx, ty = toward
    dx, dy = tx - cx, ty - cy
    if abs(dx) >= abs(dy):
        return (shape.x + shape.w, cy) if dx >= 0 else (shape.x, cy)
    return (cx, shape.y + shape.h) if dy >= 0 else (cx, shape.y)


def orthogonal_points(source: Shape, target: Shape) -> list[tuple[float, float]]:
    sc = center(source)
    tc = center(target)
    start = boundary_point(source, tc)
    end = boundary_point(target, sc)
    if abs(start[1] - end[1]) < 3 or abs(start[0] - end[0]) < 3:
        return [start, end]
    if abs(end[0] - start[0]) >= abs(end[1] - start[1]):
        mid_x = (start[0] + end[0]) / 2
        return [start, (mid_x, start[1]), (mid_x, end[1]), end]
    mid_y = (start[1] + end[1]) / 2
    return [start, (start[0], mid_y), (end[0], mid_y), end]


def draw_arrow(draw: ImageDraw.ImageDraw, p1: tuple[float, float], p2: tuple[float, float], fill: str = BLACK) -> None:
    angle = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    size = 10
    spread = math.radians(28)
    left = (p2[0] - size * math.cos(angle - spread), p2[1] - size * math.sin(angle - spread))
    right = (p2[0] - size * math.cos(angle + spread), p2[1] - size * math.sin(angle + spread))
    draw.polygon([p2, left, right], fill=fill)


def draw_open_arrow(draw: ImageDraw.ImageDraw, p1: tuple[float, float], p2: tuple[float, float]) -> None:
    angle = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    size = 12
    spread = math.radians(30)
    left = (p2[0] - size * math.cos(angle - spread), p2[1] - size * math.sin(angle - spread))
    right = (p2[0] - size * math.cos(angle + spread), p2[1] - size * math.sin(angle + spread))
    draw.line((left[0], left[1], p2[0], p2[1], right[0], right[1]), fill=BLACK, width=2)


def draw_hollow_triangle(draw: ImageDraw.ImageDraw, p1: tuple[float, float], p2: tuple[float, float]) -> None:
    angle = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    size = 16
    spread = math.radians(30)
    left = (p2[0] - size * math.cos(angle - spread), p2[1] - size * math.sin(angle - spread))
    right = (p2[0] - size * math.cos(angle + spread), p2[1] - size * math.sin(angle + spread))
    draw.polygon([p2, left, right], fill=WHITE, outline=BLACK)
    draw.line((p2[0], p2[1], left[0], left[1], right[0], right[1], p2[0], p2[1]), fill=BLACK, width=2)


def draw_diamond_marker(
    draw: ImageDraw.ImageDraw,
    endpoint: tuple[float, float],
    adjacent: tuple[float, float],
    *,
    filled: bool,
) -> None:
    dx = adjacent[0] - endpoint[0]
    dy = adjacent[1] - endpoint[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    long = 22
    half = 8
    points = [
        endpoint,
        (endpoint[0] + ux * long / 2 + nx * half, endpoint[1] + uy * long / 2 + ny * half),
        (endpoint[0] + ux * long, endpoint[1] + uy * long),
        (endpoint[0] + ux * long / 2 - nx * half, endpoint[1] + uy * long / 2 - ny * half),
    ]
    draw.polygon(points, fill=BLACK if filled else WHITE, outline=BLACK)
    draw.line(points + [points[0]], fill=BLACK, width=2)


def connector_is_dashed(connector: Connector) -> bool:
    return connector.dashed or connector.kind in {"dependency", "implementation"}


def draw_connector_markers(draw: ImageDraw.ImageDraw, connector: Connector, points: list[tuple[float, float]]) -> None:
    if len(points) < 2:
        return
    if connector.kind in {"association_no_arrow", "erd"}:
        return
    if connector.kind == "inheritance":
        draw_hollow_triangle(draw, points[-2], points[-1])
    elif connector.kind == "implementation":
        draw_hollow_triangle(draw, points[-2], points[-1])
    elif connector.kind == "composition":
        draw_diamond_marker(draw, points[0], points[1], filled=True)
    elif connector.kind == "aggregation":
        draw_diamond_marker(draw, points[0], points[1], filled=False)
    elif connector.kind in {"dependency", "directed_association"}:
        draw_open_arrow(draw, points[-2], points[-1])
    else:
        draw_arrow(draw, points[-2], points[-1])


def draw_erd_marker(draw: ImageDraw.ImageDraw, endpoint: tuple[float, float], adjacent: tuple[float, float], marker: str) -> None:
    if not marker:
        return
    dx = adjacent[0] - endpoint[0]
    dy = adjacent[1] - endpoint[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux

    def point(distance: float, side: float = 0) -> tuple[float, float]:
        return endpoint[0] + ux * distance + nx * side, endpoint[1] + uy * distance + ny * side

    def bar(distance: float) -> None:
        a = point(distance, -10)
        b = point(distance, 10)
        draw.line((a[0], a[1], b[0], b[1]), fill=BLACK, width=2)

    if "o" in marker:
        cx, cy = point(10)
        draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), outline=BLACK, width=2)
    if "|" in marker:
        bar(20 if "o" in marker else 10)
        if marker.count("|") > 1:
            bar(18)
    if "{" in marker or "}" in marker:
        base = point(28)
        for side in (-12, 0, 12):
            toe = point(14, side)
            draw.line((base[0], base[1], toe[0], toe[1]), fill=BLACK, width=2)


def draw_polyline(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    *,
    dashed: bool = False,
    arrow: bool = True,
    width: int = 2,
) -> None:
    if len(points) < 2:
        return
    if dashed:
        for a, b in zip(points, points[1:]):
            draw_dashed_line(draw, a, b, width=width)
    else:
        draw.line(points, fill=BLACK, width=width)
    if arrow:
        draw_arrow(draw, points[-2], points[-1])


def connector_points(connector: Connector, shape_map: dict[str, Shape]) -> list[tuple[float, float]]:
    source = shape_map.get(connector.source)
    target = shape_map.get(connector.target)
    if connector.points:
        return connector.points
    if source and target:
        return orthogonal_points(source, target)
    return []


def longest_segment_midpoint(points: list[tuple[float, float]]) -> tuple[float, float]:
    if len(points) < 2:
        return points[0] if points else (0, 0)
    best = (points[0], points[1], -1.0)
    for a, b in zip(points, points[1:]):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length > best[2]:
            best = (a, b, length)
    a, b, _ = best
    return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2


def longest_segment(points: list[tuple[float, float]]) -> tuple[tuple[float, float], tuple[float, float]]:
    if len(points) < 2:
        point = points[0] if points else (0, 0)
        return point, point
    return max(zip(points, points[1:]), key=lambda pair: math.hypot(pair[1][0] - pair[0][0], pair[1][1] - pair[0][1]))


def distance_to_segment(point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    px, py = point
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    projection = (ax + t * dx, ay + t * dy)
    return math.hypot(px - projection[0], py - projection[1])


def nearest_point_on_segment(point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    px, py = point
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return a
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return ax + t * dx, ay + t * dy


def nearest_segment(points: list[tuple[float, float]], anchor: tuple[float, float]) -> tuple[tuple[float, float], tuple[float, float]]:
    if len(points) < 2:
        point = points[0] if points else (0, 0)
        return point, point
    return min(zip(points, points[1:]), key=lambda pair: distance_to_segment(anchor, pair[0], pair[1]))


def expanded_box(box: tuple[float, float, float, float], margin: float = 6) -> tuple[float, float, float, float]:
    left, top, right, bottom = box
    return left - margin, top - margin, right + margin, bottom + margin


def label_obstacle_boxes(shape: Shape) -> list[tuple[float, float, float, float]]:
    if shape.kind in {"boundary", "group", "fragment"} and shape.text:
        boxes = [(shape.x, shape.y, shape.x + min(shape.w, 360), shape.y + 38)]
        if shape.kind == "fragment":
            border = 5
            boxes.extend(
                [
                    (shape.x, shape.y, shape.x + shape.w, shape.y + border),
                    (shape.x, shape.y + shape.h - border, shape.x + shape.w, shape.y + shape.h),
                    (shape.x, shape.y, shape.x + border, shape.y + shape.h),
                    (shape.x + shape.w - border, shape.y, shape.x + shape.w, shape.y + shape.h),
                ]
            )
        return boxes
    return []


def boxes_intersect(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def point_inside_box(point: tuple[float, float], box: tuple[float, float, float, float]) -> bool:
    x, y = point
    left, top, right, bottom = box
    return left < x < right and top < y < bottom


def segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    def orient(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on_segment(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> bool:
        return (
            min(p[0], r[0]) - 0.01 <= q[0] <= max(p[0], r[0]) + 0.01
            and min(p[1], r[1]) - 0.01 <= q[1] <= max(p[1], r[1]) + 0.01
        )

    o1 = orient(a, b, c)
    o2 = orient(a, b, d)
    o3 = orient(c, d, a)
    o4 = orient(c, d, b)
    if abs(o1) < 0.01 and on_segment(a, c, b):
        return True
    if abs(o2) < 0.01 and on_segment(a, d, b):
        return True
    if abs(o3) < 0.01 and on_segment(c, a, d):
        return True
    if abs(o4) < 0.01 and on_segment(c, b, d):
        return True
    return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0)


def segment_intersects_box(
    a: tuple[float, float],
    b: tuple[float, float],
    box: tuple[float, float, float, float],
) -> bool:
    left, top, right, bottom = box
    if point_inside_box(a, box) or point_inside_box(b, box):
        return True
    edges = [
        ((left, top), (right, top)),
        ((right, top), (right, bottom)),
        ((right, bottom), (left, bottom)),
        ((left, bottom), (left, top)),
    ]
    return any(segments_intersect(a, b, edge[0], edge[1]) for edge in edges)


def polyline_intersects_box(points: list[tuple[float, float]], box: tuple[float, float, float, float]) -> bool:
    return any(segment_intersects_box(a, b, box) for a, b in zip(points, points[1:]))


def label_box_at(text: str, x: float, y: float, font: ImageFont.ImageFont = FONT_SMALL) -> tuple[float, float, float, float]:
    probe = Image.new("RGB", (1, 1), WHITE)
    draw = ImageDraw.Draw(probe)
    tw, th = text_bbox(draw, text, font)
    return x - 4, y - 3, x + tw + 4, y + th + 3


def label_candidates(
    text: str,
    points: list[tuple[float, float]],
    anchor: tuple[float, float] | None,
    font: ImageFont.ImageFont = FONT_SMALL,
) -> list[tuple[float, float]]:
    probe = Image.new("RGB", (1, 1), WHITE)
    draw = ImageDraw.Draw(probe)
    tw, th = text_bbox(draw, text, font)
    candidates: list[tuple[float, float]] = []
    if len(points) < 2:
        candidates.append((points[0][0], points[0][1]) if points else (0, 0))
        return candidates
    segments = list(zip(points, points[1:]))
    if anchor:
        primary = nearest_segment(points, anchor)
        ordered_segments = [primary] + [segment for segment in sorted(segments, key=lambda pair: math.hypot(pair[1][0] - pair[0][0], pair[1][1] - pair[0][1]), reverse=True) if segment != primary]
    else:
        ordered_segments = sorted(segments, key=lambda pair: math.hypot(pair[1][0] - pair[0][0], pair[1][1] - pair[0][1]), reverse=True)
    if anchor:
        anchor_segment = nearest_segment(points, anchor)
        if distance_to_segment(anchor, anchor_segment[0], anchor_segment[1]) <= 72:
            candidates.append(anchor)
    gaps = (10, 16, 24, 34, 48, 68, 94, 128, 176, 236, 310, 400)
    for a, b in ordered_segments[:4]:
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        dx, dy = b[0] - a[0], b[1] - a[1]
        side_x = 1 if not anchor or anchor[0] >= mx else -1
        side_y = -1 if not anchor or anchor[1] < my else 1
        if abs(dx) >= abs(dy) * 1.2:
            first = -1 if side_y < 0 else 1
            for direction in (first, -first):
                for gap in gaps:
                    y = my - th - gap if direction < 0 else my + gap
                    candidates.append((mx - tw / 2, y))
            continue
        if abs(dy) >= abs(dx) * 1.2:
            first = 1 if side_x >= 0 else -1
            for direction in (first, -first):
                for gap in gaps:
                    x = mx + gap if direction > 0 else mx - tw - gap
                    candidates.append((x, my - th / 2))
            continue
        length = max(1.0, math.hypot(dx, dy))
        nx, ny = -dy / length, dx / length
        first = 1 if anchor and (anchor[0] - mx) * nx + (anchor[1] - my) * ny >= 0 else -1
        for direction in (first, -first):
            for gap in gaps:
                candidates.append((mx + nx * gap * direction - tw / 2, my + ny * gap * direction - th / 2))
    return candidates


def choose_label_position(
    text: str,
    points: list[tuple[float, float]],
    anchor: tuple[float, float] | None,
    occupied: list[tuple[float, float, float, float]],
    canvas_size: tuple[int, int],
    font: ImageFont.ImageFont = FONT_SMALL,
) -> tuple[float, float]:
    candidates = label_candidates(text, points, anchor, font)
    width, height = canvas_size
    best = candidates[0]
    best_penalty = float("inf")
    for x, y in candidates:
        box = label_box_at(text, x, y, font)
        penalty = 0
        if box[0] < 0 or box[1] < 0 or box[2] > width or box[3] > height:
            penalty += 1000
        penalty += 10000 * sum(1 for item in occupied if boxes_intersect(box, item))
        if polyline_intersects_box(points, expanded_box(box, 2)):
            penalty += 500
        nearest = nearest_segment(points, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2))
        penalty += distance_to_segment(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), nearest[0], nearest[1]) * 1.2
        if penalty < best_penalty:
            best = (x, y)
            best_penalty = penalty
        if penalty == 0:
            return x, y
    return best


def draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    a: tuple[float, float],
    b: tuple[float, float],
    *,
    width: int = 2,
    dash: int = 10,
    gap: int = 7,
) -> None:
    ax, ay = a
    bx, by = b
    length = math.hypot(bx - ax, by - ay)
    if length == 0:
        return
    dx, dy = (bx - ax) / length, (by - ay) / length
    pos = 0.0
    while pos < length:
        end = min(length, pos + dash)
        draw.line((ax + dx * pos, ay + dy * pos, ax + dx * end, ay + dy * end), fill=BLACK, width=width)
        pos += dash + gap


def draw_label_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: float,
    y: float,
    font: ImageFont.ImageFont = FONT_SMALL,
    *,
    center_text: bool = False,
) -> None:
    tw, th = text_bbox(draw, text, font)
    lx = x - tw / 2 if center_text else x
    ly = y - th / 2 if center_text else y
    draw.rectangle((lx - 4, ly - 3, lx + tw + 4, ly + th + 3), fill=WHITE)
    draw.multiline_text((lx, ly), text, font=font, fill=BLACK, align="center", spacing=3)


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    text: str,
    font: ImageFont.ImageFont = FONT,
    fill: str = BLACK,
) -> None:
    x, y, w, h = box
    start_size = font.size if hasattr(font, "size") else 16
    wrapped, font = fitted_text(draw, text, w - 12, h - 8, bold=font == FONT_BOLD, start_size=start_size)
    tw, th = text_bbox(draw, wrapped, font)
    draw.multiline_text((x + (w - tw) / 2, y + (h - th) / 2), wrapped, font=font, fill=fill, align="center", spacing=4)


def draw_shape(draw: ImageDraw.ImageDraw, shape: Shape) -> None:
    x, y, w, h = shape.x, shape.y, shape.w, shape.h
    box = (x, y, x + w, y + h)
    if shape.kind == "lifeline":
        draw_dashed_line(draw, (x + w / 2, y), (x + w / 2, y + h), width=2, dash=9, gap=7)
        return
    if shape.kind == "fragment":
        draw.rectangle(box, fill=shape.fill, outline=shape.stroke, width=2)
        if shape.text:
            draw.rectangle((x + 4, y + 3, x + 12 + min(260, len(shape.text) * 8), y + 24), fill=WHITE)
            draw.text((x + 8, y + 5), shape.text, font=FONT_BOLD, fill=BLACK)
        for section in shape.sections:
            if len(section) < 2:
                continue
            try:
                offset = float(section[0])
            except ValueError:
                continue
            line_y = y + offset
            draw.line((x, line_y, x + w, line_y), fill=BLACK, width=2)
            draw.rectangle((x + 4, line_y + 3, x + 12 + min(260, len(section[1]) * 8), line_y + 24), fill=WHITE)
            draw.text((x + 8, line_y + 5), section[1], font=FONT_BOLD, fill=BLACK)
        return
    if shape.kind in {"group", "boundary"}:
        draw.rectangle(box, fill=shape.fill, outline=shape.stroke, width=2)
        if shape.text:
            draw.text((x + 10, y + 5), shape.text, font=FONT_BOLD, fill=BLACK)
        return
    if shape.kind == "ellipse":
        draw.ellipse(box, fill=shape.fill, outline=shape.stroke, width=2)
        draw_centered_text(draw, (x, y, w, h), shape.text)
        return
    if shape.kind == "diamond":
        points = [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]
        draw.polygon(points, fill=shape.fill, outline=shape.stroke)
        draw.line(points + [points[0]], fill=BLACK, width=2)
        draw_centered_text(draw, (x + 20, y + 10, w - 40, h - 20), shape.text, FONT_SMALL)
        return
    if shape.kind == "actor":
        cx = x + w / 2
        head_r = 12
        head_y = y + 8
        body_top = head_y + head_r * 2 + 2
        body_bottom = min(y + h - 42, body_top + 34)
        foot_y = min(y + h - 31, body_bottom + 25)
        arm_y = body_top + 13
        draw.ellipse((cx - head_r, head_y, cx + head_r, head_y + head_r * 2), outline=BLACK, width=2)
        draw.line((cx, body_top, cx, body_bottom), fill=BLACK, width=2)
        draw.line((cx - 22, arm_y, cx + 22, arm_y), fill=BLACK, width=2)
        draw.line((cx, body_bottom, cx - 18, foot_y), fill=BLACK, width=2)
        draw.line((cx, body_bottom, cx + 18, foot_y), fill=BLACK, width=2)
        draw_centered_text(draw, (x, y + h - 28, w, 26), shape.text, FONT_SMALL)
        return
    if shape.kind == "database":
        ellipse_h = 24
        draw.rectangle((x, y + ellipse_h / 2, x + w, y + h - ellipse_h / 2), fill=shape.fill, outline=shape.stroke, width=2)
        draw.ellipse((x, y, x + w, y + ellipse_h), fill=shape.fill, outline=shape.stroke, width=2)
        draw.arc((x, y + h - ellipse_h, x + w, y + h), 0, 180, fill=BLACK, width=2)
        draw_centered_text(draw, (x + 8, y + 16, w - 16, h - 20), shape.text)
        return
    if shape.kind == "entity":
        draw.rectangle(box, fill=shape.fill, outline=shape.stroke, width=2)
        rows = shape.sections[0] if shape.sections else []
        header_h = min(38, max(30, h * 0.22))
        row_h = max(18, (h - header_h) / max(1, len(rows)))
        draw.rectangle((x, y, x + w, y + header_h), fill=LIGHT, outline=shape.stroke, width=2)
        draw_centered_text(draw, (x + 4, y + 3, w - 8, header_h - 6), shape.header or shape.text, FONT_BOLD)
        row_y = y + header_h
        tag_w = 54
        type_w = 112
        for raw in rows:
            draw.line((x, row_y, x + w, row_y), fill=BLACK, width=1)
            parts = raw.split()
            dtype = parts[0] if parts else ""
            name = parts[1] if len(parts) > 1 else raw
            tags = " ".join(parts[2:])
            text_y = row_y + max(2, (row_h - 13) / 2)
            draw.text((x + 10, text_y + 1), tags, font=FONT_TINY, fill=BLACK)
            draw.text((x + tag_w, text_y), name, font=FONT_SMALL, fill=BLACK)
            draw.text((x + w - type_w, text_y + 1), dtype, font=FONT_TINY, fill=BLACK)
            row_y += row_h
        return
    if shape.kind in {"class", "table"}:
        draw.rectangle(box, fill=shape.fill, outline=shape.stroke, width=2)
        current_y = y
        header_h = 36
        draw.rectangle((x, current_y, x + w, current_y + header_h), fill=LIGHT, outline=shape.stroke, width=2)
        title = shape.header or shape.text
        if shape.stereotype:
            title = f"<<{shape.stereotype}>>\n{title}"
            header_h = 54
            draw.rectangle((x, y, x + w, y + header_h), fill=LIGHT, outline=shape.stroke, width=2)
        draw_centered_text(draw, (x + 4, y + 3, w - 8, header_h - 6), title, FONT_BOLD if not shape.stereotype else FONT_SMALL)
        current_y = y + header_h
        for section in shape.sections:
            draw.line((x, current_y, x + w, current_y), fill=BLACK, width=2)
            text = "\n".join(section)
            remaining_h = max(24, y + h - current_y - 8)
            wrapped, section_font = fitted_text(draw, text, w - 20, remaining_h, start_size=13, min_size=9)
            draw.multiline_text((x + 10, current_y + 8), wrapped, font=section_font, fill=BLACK, spacing=4)
            _, th = text_bbox(draw, wrapped, section_font)
            current_y += max(30, th + 16)
        return
    if shape.kind == "parallelogram":
        skew = 18
        pts = [(x + skew, y), (x + w, y), (x + w - skew, y + h), (x, y + h)]
        draw.polygon(pts, fill=shape.fill, outline=shape.stroke)
        draw.line(pts + [pts[0]], fill=BLACK, width=2)
        draw_centered_text(draw, (x + 10, y, w - 20, h), shape.text)
        return
    draw.rectangle(box, fill=shape.fill, outline=shape.stroke, width=2)
    if shape.stereotype:
        draw_centered_text(draw, (x, y + 6, w, 18), f"<<{shape.stereotype}>>", FONT_SMALL)
        draw_centered_text(draw, (x + 8, y + 28, w - 16, h - 34), shape.text)
    else:
        draw_centered_text(draw, (x + 8, y + 4, w - 16, h - 8), shape.text)


def save_png(canvas: Canvas, path: Path) -> None:
    image = Image.new("RGB", (canvas.width, canvas.height), WHITE)
    draw = ImageDraw.Draw(image)
    shape_map = canvas.shape_map()
    occupied: list[tuple[float, float, float, float]] = [
        expanded_box((shape.x, shape.y, shape.x + shape.w, shape.y + shape.h), 10)
        for shape in canvas.shapes
        if shape.kind not in {"boundary", "group", "lifeline", "fragment"}
    ]
    for shape in canvas.shapes:
        for box in label_obstacle_boxes(shape):
            occupied.append(expanded_box(box, 8))
    for shape in canvas.shapes:
        if shape.kind in {"group", "boundary", "fragment"}:
            draw_shape(draw, shape)
    for shape in canvas.shapes:
        if shape.kind == "lifeline":
            draw_shape(draw, shape)
    for connector in canvas.connectors:
        points = connector_points(connector, shape_map)
        if points:
            draw_polyline(draw, points, dashed=connector_is_dashed(connector), arrow=False)
    for shape in canvas.shapes:
        if shape.kind not in {"group", "boundary", "lifeline", "fragment"}:
            draw_shape(draw, shape)
    for connector in canvas.connectors:
        points = connector_points(connector, shape_map)
        if len(points) >= 2 and connector.kind == "erd":
            draw_erd_marker(draw, points[0], points[1], connector.start_marker)
            draw_erd_marker(draw, points[-1], points[-2], connector.end_marker)
        else:
            draw_connector_markers(draw, connector, points)
        if connector.label and points:
            label = wrap_text(connector.label.replace("\\n", "\n"), 135, FONT_SMALL)
            lx, ly = choose_label_position(label, points, connector.label_position, occupied, (canvas.width, canvas.height), FONT_SMALL)
            draw_label_box(draw, label, lx, ly)
            occupied.append(expanded_box(label_box_at(label, lx, ly, FONT_SMALL), 5))
        if connector.start_label and points:
            sx, sy = points[0]
            draw_label_box(draw, connector.start_label, sx + 8, sy - 22)
        if connector.end_label and points:
            ex, ey = points[-1]
            draw_label_box(draw, connector.end_label, ex - 18, ey + 8)
    image.save(path)


def style_for_shape(shape: Shape) -> str:
    base = "whiteSpace=wrap;html=1;rounded=0;shadow=0;fontFamily=Helvetica;strokeColor=#000000;fillColor=#ffffff;strokeWidth=1;"
    if shape.kind in {"group", "boundary"}:
        return "swimlane;html=1;rounded=0;shadow=0;startSize=28;collapsible=0;fontStyle=1;strokeColor=#000000;fillColor=#ffffff;strokeWidth=1;"
    if shape.kind == "fragment":
        return "shape=rect;html=1;rounded=0;shadow=0;whiteSpace=wrap;fontStyle=1;strokeColor=#000000;fillColor=#ffffff;strokeWidth=1;"
    if shape.kind == "lifeline":
        return "endArrow=none;dashed=1;html=1;rounded=0;strokeColor=#000000;strokeWidth=1;"
    if shape.kind == "ellipse":
        return base + "ellipse;"
    if shape.kind == "diamond":
        return base + "rhombus;"
    if shape.kind == "actor":
        return "shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;fontFamily=Helvetica;strokeColor=#000000;fillColor=#ffffff;strokeWidth=1;"
    if shape.kind == "database":
        return base + "shape=cylinder3d;boundedLbl=1;backgroundOutline=1;size=15;"
    if shape.kind == "parallelogram":
        return base + "shape=parallelogram;perimeter=parallelogramPerimeter;fixedSize=1;"
    if shape.kind == "entity":
        return base + "align=left;verticalAlign=top;spacing=8;"
    if shape.kind in {"class", "table"}:
        return base + "align=left;verticalAlign=top;spacing=8;"
    return base


def drawio_text(text: str) -> str:
    return "<br>".join(escape(part) for part in text.replace("\\n", "\n").splitlines())


def drawio_value(shape: Shape) -> str:
    if shape.kind in {"class", "table", "entity"}:
        title = drawio_text(shape.header or shape.text)
        if shape.stereotype:
            title = f"&lt;&lt;{escape(shape.stereotype)}&gt;&gt;<br><b>{title}</b>"
        else:
            title = f"<b>{title}</b>"
        parts = [title]
        for section in shape.sections:
            parts.append("<hr>" + "<br>".join(escape(item) for item in section))
        return "".join(parts)
    if shape.stereotype:
        return f"&lt;&lt;{escape(shape.stereotype)}&gt;&gt;<br>{drawio_text(shape.text)}"
    return drawio_text(shape.text)


def style_for_connector(connector: Connector) -> str:
    edge_style = "edgeStyle=orthogonalEdgeStyle;orthogonalLoop=1;"
    if connector.points and any(abs(a[0] - b[0]) >= 3 and abs(a[1] - b[1]) >= 3 for a, b in zip(connector.points, connector.points[1:])):
        edge_style = "edgeStyle=segmentEdgeStyle;"
    style = f"{edge_style}rounded=0;jettySize=auto;html=1;fontFamily=Helvetica;strokeColor=#000000;strokeWidth=1;"
    if connector.kind in {"association_no_arrow", "erd"}:
        style += "endArrow=none;"
    elif connector.kind == "inheritance":
        style += "endArrow=block;endFill=0;"
    elif connector.kind == "implementation":
        style += "endArrow=block;endFill=0;dashed=1;"
    elif connector.kind == "composition":
        style += "startArrow=diamond;startFill=1;endArrow=none;"
    elif connector.kind == "aggregation":
        style += "startArrow=diamond;startFill=0;endArrow=none;"
    elif connector.kind == "directed_association":
        style += "endArrow=open;endFill=0;"
    elif connector.kind == "dependency":
        style += "endArrow=open;dashed=1;"
    else:
        style += "endArrow=classic;endFill=1;"
    if connector.dashed:
        style += "dashed=1;"
    return style


def save_drawio(canvas: Canvas, path: Path) -> None:
    mxfile = ET.Element("mxfile", {"host": "app.diagrams.net", "agent": "diploma-toolkit", "version": "0.1.0"})
    diagram = ET.SubElement(mxfile, "diagram", {"name": canvas.title})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": str(canvas.width),
            "dy": str(canvas.height),
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": str(canvas.width),
            "pageHeight": str(canvas.height),
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
    for shape in canvas.shapes:
        attrs = {
            "id": shape.id,
            "value": drawio_value(shape),
            "style": style_for_shape(shape),
            "vertex": "1",
            "parent": shape.parent or "1",
        }
        cell = ET.SubElement(root, "mxCell", attrs)
        ET.SubElement(
            cell,
            "mxGeometry",
            {"x": f"{shape.x:.2f}", "y": f"{shape.y:.2f}", "width": f"{shape.w:.2f}", "height": f"{shape.h:.2f}", "as": "geometry"},
        )
    for connector in canvas.connectors:
        attrs = {
            "id": connector.id,
            "value": escape(connector.label),
            "style": style_for_connector(connector),
            "edge": "1",
            "parent": "1",
            "source": connector.source,
            "target": connector.target,
        }
        cell = ET.SubElement(root, "mxCell", attrs)
        geom = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        if connector.points:
            arr = ET.SubElement(geom, "Array", {"as": "points"})
            for x, y in connector.points[1:-1]:
                ET.SubElement(arr, "mxPoint", {"x": f"{x:.2f}", "y": f"{y:.2f}"})
    ET.indent(mxfile, space="  ")
    path.write_text(ET.tostring(mxfile, encoding="unicode"), encoding="utf-8")
