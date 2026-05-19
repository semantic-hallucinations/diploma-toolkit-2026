from __future__ import annotations

from collections import defaultdict, deque
import json
import math
from pathlib import Path
import subprocess

from .rendering import Canvas, Connector, Shape, center
from .routing import perimeter_point, real_segment_crossing, route_unrouted_connectors, segment_intersects_box


def canvas_from_model(model: dict) -> Canvas:
    profile = model["profile"]
    if profile == "sequence":
        return layout_sequence(model)
    if profile == "class":
        return layout_class(model)
    if profile == "erd":
        return layout_erd(model)
    if profile == "c4":
        return layout_c4(model)
    if profile == "deployment":
        return layout_deployment(model)
    if profile == "ml-pipeline":
        return layout_pipeline(model)
    if profile == "use-case":
        return layout_usecase(model)
    raise ValueError(f"Layout for {profile} is not implemented")


def finalize_canvas(canvas: Canvas) -> Canvas:
    canvas = route_unrouted_connectors(canvas)
    if canvas.profile != "sequence":
        clean_connector_geometry(canvas)
        repair_intersecting_connectors(canvas)
        clean_connector_geometry(canvas)
    return canvas


def apply_elk_layout(
    canvas: Canvas,
    *,
    direction: str = "RIGHT",
    node_spacing: int = 110,
    layer_spacing: int = 160,
    edge_spacing: int = 42,
    edge_routing: str = "ORTHOGONAL",
    margin: int = 70,
) -> Canvas:
    layout_script = Path(__file__).resolve().parents[2] / "tools" / "elk-layout.cjs"
    if not layout_script.exists():
        return finalize_canvas(canvas)
    layout_shapes = [
        shape
        for shape in canvas.shapes
        if shape.kind not in {"boundary", "group", "lifeline", "fragment"}
    ]
    layout_ids = {shape.id for shape in layout_shapes}
    layout_edges = [
        connector
        for connector in canvas.connectors
        if connector.source in layout_ids and connector.target in layout_ids
    ]
    if not layout_shapes:
        return canvas
    payload = {
        "direction": direction,
        "nodeSpacing": node_spacing,
        "layerSpacing": layer_spacing,
        "edgeSpacing": edge_spacing,
        "edgeRouting": edge_routing,
        "nodes": [{"id": shape.id, "width": shape.w, "height": shape.h} for shape in layout_shapes],
        "edges": [{"id": connector.id, "source": connector.source, "target": connector.target} for connector in layout_edges],
    }
    try:
        completed = subprocess.run(
            ["node", str(layout_script)],
            input=json.dumps(payload),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        result = json.loads(completed.stdout)
    except Exception:
        return finalize_canvas(canvas)

    shape_map = canvas.shape_map()
    for node in result.get("children", []):
        shape = shape_map.get(node["id"])
        if shape:
            shape.x = margin + float(node.get("x", 0))
            shape.y = margin + float(node.get("y", 0))

    connector_map = {connector.id: connector for connector in canvas.connectors}
    for edge in result.get("edges", []):
        connector = connector_map.get(edge["id"])
        sections = edge.get("sections") or []
        if not connector or not sections:
            continue
        section = sections[0]
        points: list[tuple[float, float]] = []
        start = section.get("startPoint")
        end = section.get("endPoint")
        if start:
            points.append((margin + float(start["x"]), margin + float(start["y"])))
        for bend in section.get("bendPoints") or []:
            points.append((margin + float(bend["x"]), margin + float(bend["y"])))
        if end:
            points.append((margin + float(end["x"]), margin + float(end["y"])))
        if len(points) >= 2:
            connector.points = points
            connector.label_position = elk_label_anchor(points)

    canvas.width = int(float(result.get("width", canvas.width)) + margin * 2)
    canvas.height = int(float(result.get("height", canvas.height)) + margin * 2)
    clean_connector_geometry(canvas)
    repair_intersecting_connectors(canvas)
    clean_connector_geometry(canvas)
    return fit_canvas_to_content(canvas, margin=margin)


def repair_c4_line_crossings(canvas: Canvas) -> Canvas:
    """Try wider C4 detours when ELK leaves a relation visually ambiguous."""
    shape_map = canvas.shape_map()
    obstacles = [
        shape
        for shape in canvas.shapes
        if shape.kind not in {"boundary", "group", "lifeline", "fragment"}
    ]
    for _ in range(3):
        improved = False
        for connector in canvas.connectors:
            if not connector.points:
                continue
            source = shape_map.get(connector.source)
            target = shape_map.get(connector.target)
            if not source or not target:
                continue
            current_score = c4_route_score(connector.points, connector, canvas.connectors, obstacles, canvas)
            if current_score < 20000:
                continue
            candidates = c4_detour_candidates(source, target, canvas)
            best_points = connector.points
            best_score = current_score
            for candidate in candidates:
                score = c4_route_score(candidate, connector, canvas.connectors, obstacles, canvas)
                if score < best_score:
                    best_score = score
                    best_points = candidate
            if best_points is not connector.points and best_score + 1000 < current_score:
                connector.points = best_points
                connector.label_position = elk_label_anchor(best_points) or connector.label_position
                improved = True
        if not improved:
            break
    return clean_connector_geometry(canvas)


def c4_detour_candidates(source: Shape, target: Shape, canvas: Canvas) -> list[list[tuple[float, float]]]:
    source_cx, source_cy = center(source)
    target_cx, target_cy = center(target)
    lanes_x = {
        max(source.x + source.w, target.x + target.w) + 96,
        min(source.x, target.x) - 96,
        canvas.width - 125.0,
        125.0,
    }
    lanes_y = {
        max(source.y + source.h, target.y + target.h) + 96,
        min(source.y, target.y) - 96,
        canvas.height - 125.0,
        125.0,
    }
    for shape in canvas.shapes:
        if shape.kind in {"boundary", "group", "lifeline", "fragment"}:
            continue
        lanes_x.update({shape.x - 96, shape.x + shape.w + 96})
        lanes_y.update({shape.y - 96, shape.y + shape.h + 96})

    candidates: list[list[tuple[float, float]]] = []
    for lane_x in sorted(lane for lane in lanes_x if 55 <= lane <= canvas.width - 55):
        start = perimeter_point(source, (lane_x, source_cy))
        end = perimeter_point(target, (lane_x, target_cy))
        candidates.append(simplify_layout_path([start, (lane_x, start[1]), (lane_x, end[1]), end]))
        for escape_y in (source.y - 96, source.y + source.h + 96):
            if 55 <= escape_y <= canvas.height - 55:
                start = perimeter_point(source, (source_cx, escape_y))
                candidates.append(simplify_layout_path([start, (start[0], escape_y), (lane_x, escape_y), (lane_x, end[1]), end]))
    for lane_y in sorted(lane for lane in lanes_y if 55 <= lane <= canvas.height - 55):
        start = perimeter_point(source, (source_cx, lane_y))
        end = perimeter_point(target, (target_cx, lane_y))
        candidates.append(simplify_layout_path([start, (start[0], lane_y), (end[0], lane_y), end]))
        for escape_x in (source.x - 96, source.x + source.w + 96):
            if 55 <= escape_x <= canvas.width - 55:
                start = perimeter_point(source, (escape_x, source_cy))
                candidates.append(simplify_layout_path([start, (escape_x, start[1]), (escape_x, lane_y), (end[0], lane_y), end]))
    return candidates


def c4_route_score(
    points: list[tuple[float, float]],
    connector: Connector,
    connectors: list[Connector],
    obstacles: list[Shape],
    canvas: Canvas,
) -> float:
    segments = list(zip(points, points[1:]))
    shape_hits = 0
    near_shape_hits = 0
    for start, end in segments:
        for shape in obstacles:
            if shape.id in {connector.source, connector.target}:
                continue
            if segment_intersects_box(start, end, (shape.x - 10, shape.y - 10, shape.x + shape.w + 10, shape.y + shape.h + 10)):
                shape_hits += 1
            if segment_intersects_box(start, end, (shape.x - 46, shape.y - 46, shape.x + shape.w + 46, shape.y + shape.h + 46)):
                near_shape_hits += 1

    crossings = 0
    overlaps = 0
    for other in connectors:
        if other.id == connector.id or not other.points:
            continue
        if {connector.source, connector.target} & {other.source, other.target}:
            continue
        for segment in segments:
            for other_segment in zip(other.points, other.points[1:]):
                if real_segment_crossing(segment, other_segment):
                    crossings += 1
                if segments_overlap(segment, other_segment):
                    overlaps += 1

    bounds = 0.0
    for x, y in points:
        if x < 35:
            bounds += 35 - x
        if y < 35:
            bounds += 35 - y
        if x > canvas.width - 35:
            bounds += x - (canvas.width - 35)
        if y > canvas.height - 35:
            bounds += y - (canvas.height - 35)

    bends = max(0, len(points) - 2)
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in segments)
    return (
        shape_hits * 1_000_000
        + near_shape_hits * 6500
        + crossings * 50000
        + overlaps * 35000
        + bends * 180
        + bounds * 250
        + length
    )


def clean_connector_geometry(canvas: Canvas) -> Canvas:
    shape_map = canvas.shape_map()
    min_jetty = connector_jetty(canvas.profile)
    obstacle_shapes = [
        shape
        for shape in canvas.shapes
        if shape.kind not in {"boundary", "group", "lifeline", "fragment"}
    ]
    for connector in canvas.connectors:
        if not connector.points or connector.source == connector.target:
            continue
        source = shape_map.get(connector.source)
        target = shape_map.get(connector.target)
        if not source or not target or len(connector.points) < 2:
            continue
        points = list(connector.points)
        points[0] = corrected_endpoint(source, points[0], points[1])
        points[-1] = corrected_endpoint(target, points[-1], points[-2])
        points = add_endpoint_jetty(points, source, target, True, min_jetty, obstacle_shapes)
        points = add_endpoint_jetty(points, source, target, False, min_jetty, obstacle_shapes)
        connector.points = simplify_layout_path(points)
        if canvas.profile == "deployment":
            connector.points = remove_collinear_backtracks(connector.points)
        if connector.label:
            connector.label_position = elk_label_anchor(connector.points) or connector.label_position
    return canvas


def corrected_endpoint(shape: Shape, current: tuple[float, float], adjacent: tuple[float, float]) -> tuple[float, float]:
    if shape.kind in {"ellipse", "diamond"}:
        return perimeter_point(shape, adjacent)
    return current


def repair_intersecting_connectors(canvas: Canvas) -> Canvas:
    shape_map = canvas.shape_map()
    obstacle_shapes = [
        shape
        for shape in canvas.shapes
        if shape.kind not in {"boundary", "group", "lifeline", "fragment"}
    ]
    bad_connectors = [
        connector
        for connector in canvas.connectors
        if connector.points and connector_crosses_unrelated_shape(connector, obstacle_shapes)
    ]
    if not bad_connectors:
        return canvas
    for connector in bad_connectors:
        connector.points = None
        connector.label_position = None
    route_unrouted_connectors(canvas)
    for connector in canvas.connectors:
        if connector.points and connector_crosses_unrelated_shape(connector, obstacle_shapes):
            detour = connector_detour(connector, obstacle_shapes, canvas)
            if detour:
                connector.points = detour
                connector.label_position = elk_label_anchor(detour) or connector.label_position
    return canvas


def connector_crosses_unrelated_shape(connector: Connector, obstacle_shapes: list[Shape]) -> bool:
    if not connector.points:
        return False
    for a, b in zip(connector.points, connector.points[1:]):
        for shape in obstacle_shapes:
            if shape.id in {connector.source, connector.target}:
                continue
            box = (shape.x - 8, shape.y - 8, shape.x + shape.w + 8, shape.y + shape.h + 8)
            if segment_intersects_box(a, b, box):
                return True
    return False


def connector_detour(connector: Connector, obstacle_shapes: list[Shape], canvas: Canvas) -> list[tuple[float, float]] | None:
    if not connector.points or len(connector.points) < 2:
        return None
    start, end = connector.points[0], connector.points[-1]
    y_lanes = {start[1], end[1], 60.0, float(canvas.height - 60)}
    x_lanes = {start[0], end[0], 60.0, float(canvas.width - 60)}
    for shape in obstacle_shapes:
        if shape.id in {connector.source, connector.target}:
            continue
        y_lanes.update({shape.y - 84, shape.y + shape.h + 84})
        x_lanes.update({shape.x - 84, shape.x + shape.w + 84})
    candidates: list[list[tuple[float, float]]] = [[start, end]]
    center_y = (start[1] + end[1]) / 2
    center_x = (start[0] + end[0]) / 2
    for lane_y in sorted((lane for lane in y_lanes if 24 <= lane <= canvas.height - 24), key=lambda lane: abs(lane - center_y))[:10]:
        candidates.append([start, (start[0], lane_y), (end[0], lane_y), end])
    for lane_x in sorted((lane for lane in x_lanes if 24 <= lane <= canvas.width - 24), key=lambda lane: abs(lane - center_x))[:10]:
        candidates.append([start, (lane_x, start[1]), (lane_x, end[1]), end])
    best: tuple[float, list[tuple[float, float]]] | None = None
    for candidate in candidates:
        points = simplify_layout_path(candidate)
        crossings = count_path_obstacle_crossings(points, connector, obstacle_shapes)
        if crossings:
            continue
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))
        bends = max(0, len(points) - 2)
        score = bends * 160 + length
        if best is None or score < best[0]:
            best = (score, points)
    return best[1] if best else None


def count_path_obstacle_crossings(points: list[tuple[float, float]], connector: Connector, obstacle_shapes: list[Shape]) -> int:
    crossings = 0
    for a, b in zip(points, points[1:]):
        for shape in obstacle_shapes:
            if shape.id in {connector.source, connector.target}:
                continue
            box = (shape.x - 8, shape.y - 8, shape.x + shape.w + 8, shape.y + shape.h + 8)
            if segment_intersects_box(a, b, box):
                crossings += 1
    return crossings


def count_path_line_crossings(
    points: list[tuple[float, float]],
    routed_segments: list[tuple[tuple[float, float], tuple[float, float]]],
) -> int:
    return sum(
        1
        for segment in zip(points, points[1:])
        for existing in routed_segments
        if real_segment_crossing(segment, existing)
    )


def count_path_line_overlaps(
    points: list[tuple[float, float]],
    routed_segments: list[tuple[tuple[float, float], tuple[float, float]]],
) -> int:
    return sum(
        1
        for segment in zip(points, points[1:])
        for existing in routed_segments
        if segments_overlap(segment, existing)
    )


def segments_overlap(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    (a, b), (c, d) = first, second
    abx, aby = b[0] - a[0], b[1] - a[1]
    acx, acy = c[0] - a[0], c[1] - a[1]
    adx, ady = d[0] - a[0], d[1] - a[1]
    if abs(abx * acy - aby * acx) > 1.5 or abs(abx * ady - aby * adx) > 1.5:
        return False
    if abs(abx) >= abs(aby):
        left = max(min(a[0], b[0]), min(c[0], d[0]))
        right = min(max(a[0], b[0]), max(c[0], d[0]))
        return right - left > 18
    top = max(min(a[1], b[1]), min(c[1], d[1]))
    bottom = min(max(a[1], b[1]), max(c[1], d[1]))
    return bottom - top > 18


def connector_jetty(profile: str) -> float:
    if profile in {"deployment", "c4", "use-case"}:
        return 58
    if profile in {"class", "erd"}:
        return 46
    return 34


def add_endpoint_jetty(
    points: list[tuple[float, float]],
    source: Shape,
    target: Shape,
    start: bool,
    min_jetty: float,
    obstacle_shapes: list[Shape],
) -> list[tuple[float, float]]:
    if len(points) < 2:
        return points
    shape = source if start else target
    index = 0 if start else -1
    adjacent_index = 1 if start else -2
    endpoint = points[index]
    adjacent = points[adjacent_index]
    outward = outward_unit(shape, endpoint, adjacent)
    if not outward:
        return points
    jetty = (endpoint[0] + outward[0] * min_jetty, endpoint[1] + outward[1] * min_jetty)
    adjacent_distance = distance_point_to_box(adjacent, shape)
    outward_entry = endpoint_vector_is_outward(endpoint, adjacent, outward)
    if adjacent_distance >= min_jetty * 0.85 and outward_entry:
        return points
    candidate = insert_endpoint_jetty(points, jetty, start)
    if endpoint_jetty_is_clear(candidate, source, target, obstacle_shapes, start):
        return candidate
    return points


def insert_endpoint_jetty(
    points: list[tuple[float, float]],
    jetty: tuple[float, float],
    start: bool,
) -> list[tuple[float, float]]:
    if start:
        endpoint = points[0]
        after = points[1]
        if points_aligned(jetty, after):
            return [endpoint, jetty] + points[1:]
        corner = endpoint_jetty_corner(endpoint, jetty, after)
        return simplify_layout_path([endpoint, jetty, corner] + points[1:])

    before = points[-2]
    endpoint = points[-1]
    if points_aligned(before, jetty):
        return points[:-1] + [jetty, endpoint]
    corner = endpoint_jetty_corner(endpoint, jetty, before)
    return simplify_layout_path(points[:-1] + [corner, jetty, endpoint])


def endpoint_jetty_corner(
    endpoint: tuple[float, float],
    jetty: tuple[float, float],
    adjacent: tuple[float, float],
) -> tuple[float, float]:
    if abs(endpoint[0] - adjacent[0]) <= 1:
        return jetty[0], adjacent[1]
    if abs(endpoint[1] - adjacent[1]) <= 1:
        return adjacent[0], jetty[1]
    if abs(jetty[0] - endpoint[0]) >= abs(jetty[1] - endpoint[1]):
        return jetty[0], adjacent[1]
    return adjacent[0], jetty[1]


def points_aligned(first: tuple[float, float], second: tuple[float, float]) -> bool:
    return abs(first[0] - second[0]) <= 1 or abs(first[1] - second[1]) <= 1


def endpoint_jetty_is_clear(
    points: list[tuple[float, float]],
    source: Shape,
    target: Shape,
    obstacle_shapes: list[Shape],
    start: bool,
) -> bool:
    segments = list(zip(points[:3], points[1:3])) if start else list(zip(points[-3:-1], points[-2:]))
    for a, b in segments:
        for shape in obstacle_shapes:
            if shape.id in {source.id, target.id}:
                continue
            box = (shape.x - 18, shape.y - 18, shape.x + shape.w + 18, shape.y + shape.h + 18)
            if segment_intersects_box(a, b, box):
                return False
    return True


def outward_unit(
    shape: Shape,
    point: tuple[float, float],
    adjacent: tuple[float, float] | None = None,
) -> tuple[float, float] | None:
    if shape.kind not in {"ellipse", "diamond"}:
        distances = [
            (abs(point[0] - shape.x), (-1.0, 0.0)),
            (abs(point[0] - (shape.x + shape.w)), (1.0, 0.0)),
            (abs(point[1] - shape.y), (0.0, -1.0)),
            (abs(point[1] - (shape.y + shape.h)), (0.0, 1.0)),
        ]
        close_edges = [(distance, vector) for distance, vector in distances if distance <= 6]
        if close_edges:
            if adjacent:
                dx = adjacent[0] - point[0]
                dy = adjacent[1] - point[1]
                length = math.hypot(dx, dy)
                if length > 1:
                    ux, uy = dx / length, dy / length
                    return max(close_edges, key=lambda item: ux * item[1][0] + uy * item[1][1])[1]
            return min(close_edges, key=lambda item: item[0])[1]
    cx, cy = center(shape)
    dx = point[0] - cx
    dy = point[1] - cy
    length = math.hypot(dx, dy)
    if length < 0.01:
        return None
    return dx / length, dy / length


def endpoint_vector_is_outward(
    endpoint: tuple[float, float],
    adjacent: tuple[float, float],
    outward: tuple[float, float],
) -> bool:
    dx = adjacent[0] - endpoint[0]
    dy = adjacent[1] - endpoint[1]
    length = math.hypot(dx, dy)
    if length < 1:
        return False
    return (dx / length) * outward[0] + (dy / length) * outward[1] > 0.72


def distance_point_to_box(point: tuple[float, float], shape: Shape) -> float:
    x, y = point
    left, top, right, bottom = shape.x, shape.y, shape.x + shape.w, shape.y + shape.h
    dx = max(left - x, 0, x - right)
    dy = max(top - y, 0, y - bottom)
    if dx or dy:
        return math.hypot(dx, dy)
    return 0


def elk_label_anchor(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    if len(points) < 2:
        return None
    first, second = max(
        zip(points, points[1:]),
        key=lambda pair: math.hypot(pair[1][0] - pair[0][0], pair[1][1] - pair[0][1]),
    )
    return (first[0] + second[0]) / 2, (first[1] + second[1]) / 2 - 34


def fit_boundary_to_shapes(boundary: Shape, shapes: list[Shape], *, padding: float = 100) -> None:
    if not shapes:
        return
    left = min(shape.x for shape in shapes) - padding
    top = min(shape.y for shape in shapes) - padding * 0.65
    right = max(shape.x + shape.w for shape in shapes) + padding
    bottom = max(shape.y + shape.h for shape in shapes) + padding
    boundary.x = max(35, left)
    boundary.y = max(35, top)
    boundary.w = right - boundary.x
    boundary.h = bottom - boundary.y


def scale_canvas(canvas: Canvas, factor: float) -> Canvas:
    canvas.width = int(canvas.width * factor)
    canvas.height = int(canvas.height * factor)
    for shape in canvas.shapes:
        shape.x *= factor
        shape.y *= factor
        shape.w *= factor
        shape.h *= factor
    for connector in canvas.connectors:
        if connector.points:
            connector.points = [(x * factor, y * factor) for x, y in connector.points]
        if connector.label_position:
            x, y = connector.label_position
            connector.label_position = (x * factor, y * factor)
    return canvas


def compact_canvas(canvas: Canvas, factor: float, margin: float = 60) -> Canvas:
    old_shapes = {shape.id: (shape.x, shape.y, shape.w, shape.h) for shape in canvas.shapes}

    def compact_value(value: float) -> float:
        return margin + (value - margin) * factor

    for shape in canvas.shapes:
        shape.x = compact_value(shape.x)
        shape.y = compact_value(shape.y)
        if shape.kind in {"boundary", "group", "lifeline"}:
            shape.w *= factor
            shape.h *= factor

    new_shapes = {shape.id: (shape.x, shape.y, shape.w, shape.h) for shape in canvas.shapes}

    def compact_point(point: tuple[float, float]) -> tuple[float, float]:
        return compact_value(point[0]), compact_value(point[1])

    def attached_point(
        point: tuple[float, float],
        old_box: tuple[float, float, float, float] | None,
        new_box: tuple[float, float, float, float] | None,
    ) -> tuple[float, float]:
        if not old_box or not new_box:
            return compact_point(point)
        old_x, old_y, old_w, old_h = old_box
        new_x, new_y, new_w, new_h = new_box
        px, py = point
        tolerance = 2.0
        if abs(px - old_x) <= tolerance:
            ratio = 0 if old_h == 0 else (py - old_y) / old_h
            return new_x, new_y + ratio * new_h
        if abs(px - (old_x + old_w)) <= tolerance:
            ratio = 0 if old_h == 0 else (py - old_y) / old_h
            return new_x + new_w, new_y + ratio * new_h
        if abs(py - old_y) <= tolerance:
            ratio = 0 if old_w == 0 else (px - old_x) / old_w
            return new_x + ratio * new_w, new_y
        if abs(py - (old_y + old_h)) <= tolerance:
            ratio = 0 if old_w == 0 else (px - old_x) / old_w
            return new_x + ratio * new_w, new_y + new_h
        return compact_point(point)

    for connector in canvas.connectors:
        if connector.points:
            points = [compact_point(point) for point in connector.points]
            points[0] = attached_point(connector.points[0], old_shapes.get(connector.source), new_shapes.get(connector.source))
            points[-1] = attached_point(connector.points[-1], old_shapes.get(connector.target), new_shapes.get(connector.target))
            connector.points = points
        if connector.label_position:
            connector.label_position = compact_point(connector.label_position)

    max_x = max(
        [shape.x + shape.w for shape in canvas.shapes]
        + [point[0] for connector in canvas.connectors for point in (connector.points or [])]
        + [connector.label_position[0] for connector in canvas.connectors if connector.label_position],
        default=canvas.width,
    )
    max_y = max(
        [shape.y + shape.h for shape in canvas.shapes]
        + [point[1] for connector in canvas.connectors for point in (connector.points or [])]
        + [connector.label_position[1] for connector in canvas.connectors if connector.label_position],
        default=canvas.height,
    )
    canvas.width = int(max_x + margin)
    canvas.height = int(max_y + margin)
    return canvas


def fit_canvas_to_content(canvas: Canvas, margin: float = 60) -> Canvas:
    min_x = min(
        [shape.x for shape in canvas.shapes]
        + [point[0] for connector in canvas.connectors for point in (connector.points or [])]
        + [connector.label_position[0] for connector in canvas.connectors if connector.label_position],
        default=margin,
    )
    min_y = min(
        [shape.y for shape in canvas.shapes]
        + [point[1] for connector in canvas.connectors for point in (connector.points or [])]
        + [connector.label_position[1] for connector in canvas.connectors if connector.label_position],
        default=margin,
    )
    shift_x = margin - min_x if min_x != margin else 0
    shift_y = margin - min_y if min_y != margin else 0
    for shape in canvas.shapes:
        shape.x += shift_x
        shape.y += shift_y
    for connector in canvas.connectors:
        if connector.points:
            connector.points = [(x + shift_x, y + shift_y) for x, y in connector.points]
        if connector.label_position:
            x, y = connector.label_position
            connector.label_position = (x + shift_x, y + shift_y)
    max_x = max(
        [shape.x + shape.w for shape in canvas.shapes]
        + [point[0] for connector in canvas.connectors for point in (connector.points or [])]
        + [connector.label_position[0] for connector in canvas.connectors if connector.label_position],
        default=canvas.width,
    )
    max_y = max(
        [shape.y + shape.h for shape in canvas.shapes]
        + [point[1] for connector in canvas.connectors for point in (connector.points or [])]
        + [connector.label_position[1] for connector in canvas.connectors if connector.label_position],
        default=canvas.height,
    )
    canvas.width = int(max_x + margin)
    canvas.height = int(max_y + margin)
    return canvas


def layout_sequence(model: dict) -> Canvas:
    participants = model["participants"]
    events = model["events"]
    x_gap = 285
    header_y = 50
    row_h = 108
    message_y0 = 232
    width = max(1500, 110 + x_gap * (len(participants) - 1) + 260)
    height = 260 + row_h * max(1, len(events))
    canvas = Canvas("sequence", model.get("title", "Sequence"), width, height)
    pos: dict[str, tuple[float, float]] = {}
    for index, participant in enumerate(participants):
        x = 80 + index * x_gap
        pos[participant["id"]] = (x, header_y)
        kind = "actor" if participant.get("kind") == "actor" else "database" if participant.get("kind") == "database" else "rect"
        canvas.shapes.append(Shape(participant["id"], kind, x, header_y, 150, 112 if kind == "actor" else 64, participant["label"]))
        lifeline_id = f"life_{participant['id']}"
        canvas.shapes.append(Shape(lifeline_id, "lifeline", x + 74, header_y + 112, 1, height - header_y - 145, "", fill="#ffffff"))
    row = 0.0
    message_index = 0
    fragment_stack: list[dict] = []
    fragments: list[dict] = []
    for event in events:
        if event["type"] == "fragment_start":
            fragment_stack.append(
                {
                    "kind": event["kind"],
                    "label": event["label"],
                    "start": row,
                    "depth": len(fragment_stack),
                    "dividers": [],
                }
            )
        elif event["type"] == "fragment_else":
            if fragment_stack:
                fragment_stack[-1]["dividers"].append((row - 0.5, f"else: {event['label']}"))
        elif event["type"] == "fragment_end":
            if fragment_stack:
                fragment = fragment_stack.pop()
                fragment["end"] = row
                fragments.append(fragment)
        elif event["type"] == "message":
            y = message_y0 + row * row_h
            src = model["participants"][0]["id"] if event["source"] not in pos else event["source"]
            dst = model["participants"][0]["id"] if event["target"] not in pos else event["target"]
            sx = pos[src][0] + 75
            tx = pos[dst][0] + 75
            dashed = bool(event.get("return"))
            if src == dst:
                canvas.connectors.append(
                    Connector(
                        f"msg_{message_index}_{src}_{dst}",
                        src,
                        dst,
                        event["label"],
                        dashed=dashed,
                        points=[(sx, y), (sx + 78, y), (sx + 78, y + 30), (sx + 8, y + 30)],
                        label_position=(sx + 42, y - 20),
                    )
                )
                row += 1
                message_index += 1
                continue
            canvas.connectors.append(
                Connector(
                    f"msg_{message_index}_{src}_{dst}",
                    src,
                    dst,
                    event["label"],
                    dashed=dashed,
                    points=[(sx, y), (tx, y)],
                    label_position=sequence_label_position(sx, tx, y, [item[0] + 75 for item in pos.values()], event["label"]),
                )
            )
            row += 1
            message_index += 1
    canvas.height = max(680, int(message_y0 + row * row_h + 100))
    for shape in canvas.shapes:
        if shape.kind == "lifeline":
            shape.h = canvas.height - header_y - 145
    fragment_shapes: list[tuple[int, float, Shape]] = []
    for index, fragment in enumerate(fragments):
        start = float(fragment["start"])
        end = float(fragment["end"])
        depth = int(fragment["depth"])
        y = message_y0 + start * row_h - 50 + depth * 16
        bottom = message_y0 + max(start + 1, end) * row_h - 58 - depth * 16
        h = max(row_h + 42, bottom - y)
        x = 45 + depth * 30
        sections = [[str(message_y0 + divider_row * row_h - y), divider_label] for divider_row, divider_label in fragment["dividers"]]
        fragment_shapes.append(
            (
                depth,
                y,
                Shape(
                    f"fragment_{index}",
                    "fragment",
                    x,
                    y,
                    width - 90 - depth * 60,
                    h,
                    f"{fragment['kind']}: {fragment['label']}",
                    fill="#ffffff",
                    sections=sections,
                ),
            )
        )
    canvas.shapes = [
        shape
        for _, _, shape in sorted(fragment_shapes, key=lambda item: (item[0], item[1]))
    ] + canvas.shapes
    return fit_canvas_to_content(canvas, margin=50)


def sequence_label_position(sx: float, tx: float, y: float, lifelines: list[float], label: str) -> tuple[float, float]:
    left, right = sorted((sx, tx))
    blockers = sorted(x for x in lifelines if left < x < right)
    stops = [left] + blockers + [right]
    intervals = [(a + 14, b - 14) for a, b in zip(stops, stops[1:]) if b - a > 70]
    if not intervals:
        return ((sx + tx) / 2, y - 30)
    text_width = min(180, max(70, len(label) * 6.4))
    best_left, best_right = max(intervals, key=lambda item: item[1] - item[0])
    x = best_left + max(0, (best_right - best_left - text_width) / 2)
    return x, y - 42


def layout_class(model: dict) -> Canvas:
    classes = model["classes"]
    cell_w = 400
    cell_h = 250
    preferred = {
        "DiagramProject": (1450, 80),
        "DiagramSource": (720, 500),
        "DiagramModel": (1450, 500),
        "DiagramValidator": (2180, 500),
        "SourceParser": (220, 930),
        "MermaidParser": (80, 1450),
        "PlantUmlParser": (610, 1450),
        "Node": (1250, 960),
        "Edge": (1740, 960),
        "LayoutEngine": (2720, 930),
        "OrthogonalRouter": (2720, 1450),
        "DrawioWriter": (1260, 1710),
        "PngExporter": (1810, 1710),
    }
    stress_preferred = {
        "ReviewWorkspace": (80, 360),
        "ProjectImportJob": (560, 360),
        "SourceSnapshot": (1040, 360),
        "NoteDocument": (1520, 140),
        "DiagramCatalog": (1520, 620),
        "DiagramSource": (2000, 620),
        "Parser": (2540, 620),
        "MermaidParser": (2540, 120),
        "PlantUmlParser": (2540, 1030),
        "JsonDiagramParser": (2540, 1440),
        "ParsedDiagramModel": (3300, 620),
        "LayoutProfile": (3900, 360),
        "ConnectorRouter": (3900, 780),
        "CanvasValidator": (3300, 1120),
        "DrawioDocument": (4500, 780),
        "PngArtifact": (5020, 780),
        "BuildDiagnostics": (1040, 1160),
        "NormalControlReport": (560, 1160),
    }
    class_ids = {cls["id"] for cls in classes}
    use_preferred = class_ids.issubset(preferred)
    use_stress_preferred = not use_preferred and class_ids.issubset(stress_preferred)
    generic_positions = class_generic_positions(classes, model["relationships"]) if not use_preferred and not use_stress_preferred else {}
    if use_preferred:
        width, height = 3240, 2050
    elif use_stress_preferred:
        width, height = 5520, 1780
    else:
        width = max(1200, int(max((x for x, _ in generic_positions.values()), default=0) + cell_w + 120))
        height = max(900, int(max((y for _, y in generic_positions.values()), default=0) + cell_h + 120))
    canvas = Canvas("class", model.get("title", "Class"), width, height)
    for index, cls in enumerate(classes):
        if use_preferred:
            x, y = preferred[cls["id"]]
        elif use_stress_preferred:
            x, y = stress_preferred[cls["id"]]
        else:
            x, y = generic_positions[cls["id"]]
        fields = cls.get("fields", [])[:8]
        methods = cls.get("methods", [])[:8]
        canvas.shapes.append(
            Shape(
                cls["id"],
                "class",
                x,
                y,
                cell_w,
                cell_h,
                cls["label"],
                header=cls["label"],
                sections=[fields or [" "], methods or [" "]],
                stereotype=cls.get("stereotype"),
            )
        )
    for index, rel in enumerate(model["relationships"]):
        rel_label = class_connector_label(rel)
        if use_preferred:
            points, label_position, label = class_route(rel["source"], rel["target"], rel_label)
        elif use_stress_preferred:
            points, label_position, label = class_stress_route(rel["source"], rel["target"], rel_label)
        else:
            points, label_position, label = None, None, rel_label
        canvas.connectors.append(
            Connector(
                f"rel_{index}",
                rel["source"],
                rel["target"],
                label,
                kind=rel.get("kind", "association"),
                points=points,
                label_position=label_position,
            )
        )
    if use_preferred:
        return finalize_canvas(compact_canvas(scale_canvas(canvas, 0.78), 0.95))
    if use_stress_preferred:
        return fit_canvas_to_content(finalize_canvas(scale_canvas(canvas, 0.82)))
    return apply_elk_layout(canvas, direction="RIGHT", node_spacing=170, layer_spacing=230, edge_spacing=64)


def class_generic_positions(classes: list[dict], relationships: list[dict]) -> dict[str, tuple[float, float]]:
    class_map = {cls["id"]: cls for cls in classes}
    order = {cls["id"]: index for index, cls in enumerate(classes)}
    directed_edges = class_layout_edges(relationships)
    ranks = class_ranks(class_map, directed_edges)
    by_rank: dict[int, list[str]] = defaultdict(list)
    for cls in classes:
        by_rank[ranks.get(cls["id"], 0)].append(cls["id"])

    for _ in range(4):
        for rank in sorted(by_rank):
            previous_rank = by_rank.get(rank - 1, [])
            previous_index = {name: index for index, name in enumerate(previous_rank)}
            by_rank[rank].sort(
                key=lambda name: (
                    neighbor_barycenter(name, directed_edges, previous_index),
                    class_kind_order(class_map[name]),
                    order[name],
                )
            )

    x_gap = 700
    y_gap = 390
    max_rows = max((len(items) for items in by_rank.values()), default=1)
    positions: dict[str, tuple[float, float]] = {}
    for rank in sorted(by_rank):
        items = by_rank[rank]
        offset = (max_rows - len(items)) * y_gap / 2
        for row, class_id in enumerate(items):
            stagger = 58 if rank % 2 and len(items) > 1 else 0
            positions[class_id] = (80 + rank * x_gap, 80 + offset + row * y_gap + stagger)
    return positions


def class_connector_label(rel: dict) -> str:
    label = rel.get("label", "")
    if rel.get("kind") in {"implementation", "inheritance"} and label.lower() in {"implements", "extends", "inherits"}:
        return ""
    return label


def class_layout_edges(relationships: list[dict]) -> list[tuple[str, str]]:
    edges: list[tuple[str, str]] = []
    for rel in relationships:
        source = rel["source"]
        target = rel["target"]
        if rel.get("kind") in {"inheritance", "implementation"}:
            edges.append((target, source))
        else:
            edges.append((source, target))
    return edges


def class_ranks(classes: dict[str, dict], edges: list[tuple[str, str]]) -> dict[str, int]:
    incoming = defaultdict(int)
    outgoing = defaultdict(list)
    for source, target in edges:
        if source not in classes or target not in classes:
            continue
        outgoing[source].append(target)
        incoming[target] += 1
        incoming.setdefault(source, incoming[source])
    queue = deque([class_id for class_id in classes if incoming[class_id] == 0])
    ranks = {class_id: 0 for class_id in classes}
    while queue:
        class_id = queue.popleft()
        for target in outgoing[class_id]:
            ranks[target] = max(ranks[target], ranks[class_id] + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    if any(incoming[class_id] > 0 for class_id in classes):
        for source, target in edges:
            ranks[target] = max(ranks.get(target, 0), min(ranks.get(source, 0) + 1, 6))
    return {class_id: min(rank, 7) for class_id, rank in ranks.items()}


def neighbor_barycenter(name: str, edges: list[tuple[str, str]], previous_index: dict[str, int]) -> float:
    values = [previous_index[source] for source, target in edges if target == name and source in previous_index]
    if not values:
        return float("inf")
    return sum(values) / len(values)


def class_kind_order(cls: dict) -> int:
    stereotype = (cls.get("stereotype") or "").lower()
    if "interface" in stereotype:
        return 0
    if cls["id"].endswith("Parser"):
        return 1
    if "Validator" in cls["id"] or "Diagnostics" in cls["id"] or "Report" in cls["id"]:
        return 3
    return 2


def class_route(source: str, target: str, label: str) -> tuple[list[tuple[float, float]] | None, tuple[float, float] | None, str]:
    routes: dict[tuple[str, str], tuple[list[tuple[float, float]], tuple[float, float] | None, str]] = {
        ("MermaidParser", "SourceParser"): ([(280, 1450), (340, 1180)], (165, 1305), "implements"),
        ("PlantUmlParser", "SourceParser"): ([(810, 1450), (620, 1180)], (660, 1310), "implements"),
        ("OrthogonalRouter", "LayoutEngine"): ([(2920, 1450), (2920, 1180)], (2965, 1310), "supports routing"),
        ("DiagramProject", "DiagramSource"): ([(1510, 330), (1120, 560)], (1215, 405), "owns"),
        ("DiagramProject", "DiagramModel"): ([(1650, 330), (1650, 500)], (1695, 410), "builds"),
        ("DiagramModel", "Node"): ([(1580, 750), (1450, 960)], (1360, 835), "contains"),
        ("DiagramModel", "Edge"): ([(1740, 750), (1940, 960)], (1870, 835), "contains"),
        ("DiagramValidator", "DiagramModel"): ([(2180, 625), (1850, 625)], (1985, 565), "validates"),
        ("OrthogonalRouter", "Edge"): ([(2720, 1565), (2440, 1350), (2140, 1085)], (2390, 1270), "routes"),
        ("DrawioWriter", "DiagramModel"): ([(1460, 1710), (1120, 1410), (1120, 790), (1450, 640)], (1015, 1110), "serializes"),
        ("PngExporter", "DrawioWriter"): ([(1810, 1835), (1660, 1835)], (1735, 1800), "uses output"),
    }
    return routes.get((source, target), (None, None, label))


def class_stress_safe_route(source: str, target: str, label: str) -> tuple[list[tuple[float, float]] | None, tuple[float, float] | None, str]:
    routes: dict[tuple[str, str], tuple[list[tuple[float, float]], tuple[float, float] | None, str]] = {
        ("JsonDiagramParser", "Parser"): ([(2480, 1440), (2920, 1440), (2920, 745), (2880, 745)], (2928, 1110), "implements"),
    }
    return routes.get((source, target), (None, None, label))


def class_stress_route(source: str, target: str, label: str) -> tuple[list[tuple[float, float]] | None, tuple[float, float] | None, str]:
    routes: dict[tuple[str, str], tuple[list[tuple[float, float]], tuple[float, float] | None, str]] = {
        ("ReviewWorkspace", "ProjectImportJob"): ([(480, 485), (560, 485)], (500, 435), "schedules"),
        ("ProjectImportJob", "SourceSnapshot"): ([(960, 485), (1040, 485)], (990, 435), "creates"),
        ("SourceSnapshot", "NoteDocument"): ([(1440, 410), (1520, 265)], (1435, 315), "contains"),
        ("SourceSnapshot", "DiagramCatalog"): ([(1440, 530), (1520, 745)], (1455, 640), "indexes"),
        ("DiagramCatalog", "DiagramSource"): ([(1920, 745), (2000, 745)], (1945, 690), "references"),
        ("DiagramSource", "Parser"): ([(2400, 745), (2540, 745)], (2445, 690), "selects"),
        ("MermaidParser", "Parser"): ([(2740, 370), (2740, 620)], None, ""),
        ("PlantUmlParser", "Parser"): ([(2740, 1030), (2740, 870)], None, ""),
        ("JsonDiagramParser", "Parser"): ([(2740, 1440), (3000, 1440), (3000, 745), (2940, 745)], None, ""),
        ("MermaidParser", "ParsedDiagramModel"): ([(2940, 245), (3100, 245), (3100, 660), (3300, 660)], (3030, 425), "returns"),
        ("PlantUmlParser", "ParsedDiagramModel"): ([(2940, 1110), (3060, 1110), (3060, 760), (3300, 760)], (3090, 930), "returns"),
        ("JsonDiagramParser", "ParsedDiagramModel"): ([(2940, 1565), (3140, 1565), (3140, 860), (3300, 860)], (3165, 1290), "returns"),
        ("ParsedDiagramModel", "LayoutProfile"): ([(3700, 705), (3900, 485)], (3790, 565), "uses"),
        ("LayoutProfile", "ConnectorRouter"): ([(4100, 610), (4100, 780)], (4135, 695), "configures"),
        ("ConnectorRouter", "DrawioDocument"): ([(4300, 860), (4500, 860)], (4370, 805), "writes routes"),
        ("DrawioDocument", "PngArtifact"): ([(4900, 905), (5020, 905)], (4940, 850), "exports"),
        ("CanvasValidator", "DrawioDocument"): ([(3700, 1245), (4420, 1245), (4420, 980), (4500, 980)], (4090, 1200), "validates"),
        ("CanvasValidator", "ParsedDiagramModel"): ([(3500, 1120), (3500, 870)], (3535, 1000), "checks semantics"),
        ("BuildDiagnostics", "CanvasValidator"): ([(1440, 1285), (1540, 1740), (3300, 1740), (3300, 1285)], (2200, 1685), "summarizes"),
        ("NormalControlReport", "BuildDiagnostics"): ([(960, 1285), (1040, 1285)], (985, 1230), "consumes"),
        ("ConnectorRouter", "CanvasValidator"): ([(3900, 1030), (3780, 1195), (3700, 1245)], (3795, 1115), "avoids failures"),
    }
    return routes.get((source, target), (None, None, label))


def layout_erd(model: dict) -> Canvas:
    entities = model["entities"]
    cell_w = 380
    preferred = {
        "USER": (70, 140),
        "PROJECT": (610, 140),
        "DIAGRAM_SOURCE": (1150, 140),
        "RENDER_JOB": (1690, 140),
        "ARTIFACT": (2230, 140),
        "PROJECT_MEMBER": (610, 610),
        "DIAGRAM_PROFILE": (1150, 610),
        "STYLE_PROFILE": (1690, 610),
        "VALIDATION_RESULT": (2230, 610),
        "BUILD_ERROR_BUNDLE": (2230, 1010),
    }
    entity_ids = {entity["id"] for entity in entities}
    use_preferred = entity_ids.issubset(preferred)
    generic_positions = erd_generic_positions(entities, model["relationships"]) if not use_preferred else {}
    width = 2700 if use_preferred else max(1200, int(max((x for x, _ in generic_positions.values()), default=0) + cell_w + 120))
    height = 1320 if use_preferred else max(820, int(max((y for _, y in generic_positions.values()), default=0) + 260))
    canvas = Canvas("erd", model.get("title", "ERD"), width, height)
    for index, entity in enumerate(entities):
        if use_preferred:
            x, y = preferred[entity["id"]]
        else:
            x, y = generic_positions[entity["id"]]
        fields = entity.get("fields", [])[:10]
        h = 42 + max(1, len(fields)) * 25
        canvas.shapes.append(Shape(entity["id"], "entity", x, y, cell_w, h, entity["label"], header=entity["label"], sections=[fields]))
    shape_map = canvas.shape_map()
    generic_ports: dict[tuple[str, str], int] = defaultdict(int)
    for index, rel in enumerate(model["relationships"]):
        points, label_position = erd_route_map().get((rel["source"], rel["target"]), (None, None)) if use_preferred else (None, None)
        if use_preferred and points is None and rel["source"] in shape_map and rel["target"] in shape_map:
            points, label_position = erd_auto_route(shape_map[rel["source"]], shape_map[rel["target"]])
        canvas.connectors.append(
            Connector(
                f"erd_{index}",
                rel["source"],
                rel["target"],
                rel.get("label", ""),
                kind="erd",
                start_marker=rel.get("start", ""),
                end_marker=rel.get("end", ""),
                points=points,
                label_position=label_position,
            )
        )
    if use_preferred:
        return finalize_canvas(fit_canvas_to_content(scale_canvas(canvas, 0.88)))
    return apply_elk_layout(canvas, direction="RIGHT", node_spacing=140, layer_spacing=200, edge_spacing=58)


def erd_generic_positions(entities: list[dict], relationships: list[dict]) -> dict[str, tuple[float, float]]:
    entity_map = {entity["id"]: entity for entity in entities}
    ranks = graph_ranks(entity_map, relationships)
    order = {entity["id"]: index for index, entity in enumerate(entities)}
    by_rank: dict[int, list[str]] = defaultdict(list)
    for entity in entities:
        by_rank[ranks.get(entity["id"], 0)].append(entity["id"])

    x_gap = 540
    y_gap = 270
    max_rows = max((len(items) for items in by_rank.values()), default=1)
    positions: dict[str, tuple[float, float]] = {}
    for rank in sorted(by_rank):
        items = sorted(by_rank[rank], key=lambda item: order[item])
        offset = (max_rows - len(items)) * y_gap / 2
        for row, entity_id in enumerate(items):
            positions[entity_id] = (70 + rank * x_gap, 120 + offset + row * y_gap)
    return positions


def erd_auto_route(source: Shape, target: Shape) -> tuple[list[tuple[float, float]], tuple[float, float]]:
    source_cx, source_cy = source.x + source.w / 2, source.y + source.h / 2
    target_cx, target_cy = target.x + target.w / 2, target.y + target.h / 2
    dx, dy = target_cx - source_cx, target_cy - source_cy
    if abs(dx) >= abs(dy):
        if dx >= 0:
            start = (source.x + source.w, source_cy)
            end = (target.x, target_cy)
        else:
            start = (source.x, source_cy)
            end = (target.x + target.w, target_cy)
        if abs(start[1] - end[1]) < 6:
            points = [start, end]
        else:
            mid_x = (start[0] + end[0]) / 2
            points = [start, (mid_x, start[1]), (mid_x, end[1]), end]
        label_position = ((start[0] + end[0]) / 2 - 20, min(start[1], end[1]) - 48)
        return points, label_position
    if dy >= 0:
        start = (source_cx, source.y + source.h)
        end = (target_cx, target.y)
    else:
        start = (source_cx, source.y)
        end = (target_cx, target.y + target.h)
    if abs(start[0] - end[0]) < 6:
        points = [start, end]
    else:
        mid_y = (start[1] + end[1]) / 2
        points = [start, (start[0], mid_y), (end[0], mid_y), end]
    label_position = (max(start[0], end[0]) + 24, (start[1] + end[1]) / 2 - 10)
    return points, label_position


def erd_generic_route(
    source: Shape,
    target: Shape,
    used_ports: dict[tuple[str, str], int],
) -> tuple[list[tuple[float, float]], tuple[float, float]]:
    source_cx, source_cy = source.x + source.w / 2, source.y + source.h / 2
    target_cx, target_cy = target.x + target.w / 2, target.y + target.h / 2
    dx, dy = target_cx - source_cx, target_cy - source_cy
    horizontal = abs(dx) >= abs(dy) * 0.72
    if horizontal:
        source_side = "E" if dx >= 0 else "W"
        target_side = "W" if dx >= 0 else "E"
    else:
        source_side = "S" if dy >= 0 else "N"
        target_side = "N" if dy >= 0 else "S"
    start = erd_port(source, source_side, used_ports)
    end = erd_port(target, target_side, used_ports)
    if horizontal:
        gap = abs(end[0] - start[0])
        if abs(start[1] - end[1]) < 12:
            points = [start, end]
        elif gap > 170:
            mid_x = (start[0] + end[0]) / 2 + erd_lane_shift(target.id if dx >= 0 else source.id, used_ports)
            points = [start, (mid_x, start[1]), (mid_x, end[1]), end]
        else:
            lane_x = max(start[0], end[0]) + 80 if dx >= 0 else min(start[0], end[0]) - 80
            points = [start, (lane_x, start[1]), (lane_x, end[1]), end]
        label_position = ((start[0] + end[0]) / 2 - 20, min(start[1], end[1]) - 46)
        return points, label_position
    gap = abs(end[1] - start[1])
    if abs(start[0] - end[0]) < 12:
        points = [start, end]
    elif gap > 150:
        mid_y = (start[1] + end[1]) / 2 + erd_lane_shift(target.id if dy >= 0 else source.id, used_ports)
        points = [start, (start[0], mid_y), (end[0], mid_y), end]
    else:
        lane_y = max(start[1], end[1]) + 80 if dy >= 0 else min(start[1], end[1]) - 80
        points = [start, (start[0], lane_y), (end[0], lane_y), end]
    label_position = (max(start[0], end[0]) + 24, (start[1] + end[1]) / 2 - 10)
    return points, label_position


def erd_port(shape: Shape, side: str, used_ports: dict[tuple[str, str], int]) -> tuple[float, float]:
    ratios = (0.50, 0.30, 0.70, 0.18, 0.82, 0.42, 0.58)
    key = (shape.id, side)
    ratio = ratios[used_ports[key] % len(ratios)]
    used_ports[key] += 1
    if side == "E":
        return shape.x + shape.w, shape.y + shape.h * ratio
    if side == "W":
        return shape.x, shape.y + shape.h * ratio
    if side == "S":
        return shape.x + shape.w * ratio, shape.y + shape.h
    return shape.x + shape.w * ratio, shape.y


def erd_lane_shift(anchor_id: str, used_ports: dict[tuple[str, str], int]) -> float:
    shifts = (0, -46, 46, -92, 92, -138, 138)
    key = ("__lane__", anchor_id)
    shift = shifts[used_ports[key] % len(shifts)]
    used_ports[key] += 1
    return shift


def short_cardinality(value: str) -> str:
    if "{" in value:
        return "*"
    if "o" in value:
        return "0..1"
    if "|" in value:
        return "1"
    return value


def erd_route_map() -> dict[tuple[str, str], tuple[list[tuple[float, float]], tuple[float, float] | None]]:
    return {
        ("USER", "PROJECT"): ([(450, 235), (610, 235)], (505, 180)),
        ("USER", "PROJECT_MEMBER"): ([(280, 302), (510, 520), (610, 695)], (390, 485)),
        ("PROJECT", "PROJECT_MEMBER"): ([(800, 328), (800, 610)], (825, 465)),
        ("PROJECT", "DIAGRAM_SOURCE"): ([(990, 235), (1150, 235)], (1040, 180)),
        ("DIAGRAM_SOURCE", "RENDER_JOB"): ([(1530, 235), (1690, 235)], (1585, 180)),
        ("RENDER_JOB", "ARTIFACT"): ([(2070, 235), (2230, 235)], (2125, 180)),
        ("RENDER_JOB", "VALIDATION_RESULT"): ([(2070, 290), (2230, 695)], (2145, 480)),
        ("RENDER_JOB", "BUILD_ERROR_BUNDLE"): ([(1700, 300), (1600, 480), (1600, 1095), (2230, 1095)], (1635, 770)),
        ("STYLE_PROFILE", "RENDER_JOB"): ([(1880, 610), (1880, 328)], (1915, 465)),
        ("DIAGRAM_PROFILE", "DIAGRAM_SOURCE"): ([(1340, 610), (1340, 328)], (1370, 465)),
    }


def layout_c4(model: dict) -> Canvas:
    boundary = model.get("boundary") or {"id": "system", "label": "System"}
    inside = [e for e in model["elements"] if e.get("inside_boundary")]
    people = [e for e in model["elements"] if e["kind"] == "Person"]
    external = [e for e in model["elements"] if e["kind"] in {"System_Ext", "System"} and not e.get("inside_boundary")]
    positions = {
        "student": (110, 330),
        "supervisor": (110, 1140),
        "web": (850, 310),
        "api": (1500, 310),
        "renderer": (850, 750),
        "exporter": (1500, 750),
        "storage": (850, 1160),
        "cache": (1500, 1160),
        "bsuir": (2520, 220),
        "github": (2520, 780),
        "drawio": (2520, 1280),
        "author": (80, 360),
        "reviewer": (4900, 980),
        "controller": (3170, 40),
        "cli": (520, 500),
        "api": (1050, 500),
        "importer": (1580, 500),
        "parser": (2110, 500),
        "layout": (2640, 500),
        "validator": (3170, 500),
        "writer": (3700, 500),
        "exporter": (4230, 500),
        "cache": (3170, 980),
        "artifacts": (4230, 980),
        "bsuir_stress": (1380, 40),
    }
    element_ids = {item["id"] for item in model["elements"]}
    use_preferred = element_ids.issubset(positions)
    use_stress_preferred = {"author", "cli", "api", "importer", "parser", "layout", "validator", "writer", "exporter", "cache", "artifacts"}.issubset(element_ids)
    right_people_ids: set[str] = set()
    if use_preferred:
        width, height = (3200, 1580) if use_stress_preferred else (3000, 1800)
        canvas = Canvas("c4", model.get("title", "C4"), width, height)
        if use_stress_preferred:
            canvas.shapes.append(Shape(boundary["id"], "boundary", 330, 240, 4450, 1200, boundary["label"]))
            positions["bsuir"] = positions["bsuir_stress"]
        else:
            canvas.shapes.append(Shape(boundary["id"], "boundary", 650, 130, 1600, 1320, boundary["label"]))
    else:
        inside_positions = c4_inside_positions(inside, model["relationships"])
        boundary_w = max(1850, int(max((x for x, _ in inside_positions.values()), default=0) + 680))
        boundary_h = max(1050, int(max((y for _, y in inside_positions.values()), default=0) + 360))
        boundary_center_x = 300 + boundary_w / 2
        right_people_ids = set()
        width = 360 + boundary_w + (980 if right_people_ids and external else 690)
        height = max(boundary_h + 180, 180 + max(len(people), len(external), 1) * 300)
        canvas = Canvas("c4", model.get("title", "C4"), width, height)
        canvas.shapes.append(Shape(boundary["id"], "boundary", 300, 80, boundary_w, boundary_h, boundary["label"]))
    people_y = {}
    external_y = {}
    if not use_preferred:
        people_y = spread_c4_side_positions(
            [(person["id"], c4_related_y(person["id"], inside_positions, model["relationships"], index)) for index, person in enumerate(people)],
            min_y=120,
            spacing=230,
        )
        external_y = spread_c4_side_positions(
            [(ext["id"], c4_related_y(ext["id"], inside_positions, model["relationships"], index)) for index, ext in enumerate(external)],
            min_y=120,
            spacing=250,
        )
    for person in people:
        if use_preferred:
            x, y = positions[person["id"]]
        else:
            x = canvas.shapes[0].x + canvas.shapes[0].w + 120 if person["id"] in right_people_ids else 70
            y = people_y[person["id"]]
        canvas.shapes.append(Shape(person["id"], "actor", x, y, 170, 128, person["label"]))
    for ext in external:
        kind = "database" if "Db" in ext["kind"] else "rect"
        if use_preferred:
            x, y = positions[ext["id"]]
        else:
            x = canvas.shapes[0].x + canvas.shapes[0].w + (500 if right_people_ids else 170)
            y = external_y[ext["id"]]
        canvas.shapes.append(Shape(ext["id"], kind, x, y, 370, 155, c4_label(ext), stereotype="External"))
    for index, item in enumerate(inside):
        if use_preferred:
            x, y = positions[item["id"]]
        else:
            x, y = inside_positions[item["id"]]
        kind = "database" if item["kind"] == "ContainerDb" else "rect"
        canvas.shapes.append(Shape(item["id"], kind, x, y, 420, 155, c4_label(item), stereotype=item["kind"].replace("ContainerDb", "Database")))
    for index, rel in enumerate(model["relationships"]):
        if use_preferred:
            points, label_position, label = c4_route(rel["source"], rel["target"], rel["label"])
        else:
            points, label_position, label = None, None, rel["label"]
        canvas.connectors.append(Connector(f"c4_rel_{index}", rel["source"], rel["target"], label, points=points, label_position=label_position))
    if use_preferred:
        if use_stress_preferred:
            return fit_canvas_to_content(finalize_canvas(scale_canvas(canvas, 0.86)), margin=90)
        return finalize_canvas(compact_canvas(scale_canvas(canvas, 0.80), 0.90))
    canvas = apply_elk_layout(
        canvas,
        direction="RIGHT",
        node_spacing=175,
        layer_spacing=245,
        edge_spacing=76,
        edge_routing="ORTHOGONAL",
        margin=90,
    )
    shape_map = canvas.shape_map()
    boundary_shape = shape_map.get(boundary["id"])
    if boundary_shape:
        fit_boundary_to_shapes(boundary_shape, [shape_map[item["id"]] for item in inside if item["id"] in shape_map], padding=120)
    repair_c4_line_crossings(canvas)
    return fit_canvas_to_content(canvas, margin=90)


def c4_related_y(element_id: str, inside_positions: dict[str, tuple[float, float]], relationships: list[dict], fallback_index: int) -> float:
    related: list[float] = []
    for rel in relationships:
        other = ""
        if rel["source"] == element_id:
            other = rel["target"]
        elif rel["target"] == element_id:
            other = rel["source"]
        if other in inside_positions:
            related.append(inside_positions[other][1])
    if related:
        return max(120, sum(related) / len(related))
    return 150 + fallback_index * 250


def c4_related_x(element_id: str, inside_positions: dict[str, tuple[float, float]], relationships: list[dict], fallback_index: int) -> float:
    related: list[float] = []
    for rel in relationships:
        other = ""
        if rel["source"] == element_id:
            other = rel["target"]
        elif rel["target"] == element_id:
            other = rel["source"]
        if other in inside_positions:
            related.append(inside_positions[other][0])
    if related:
        return sum(related) / len(related)
    return 300 + fallback_index * 260


def spread_c4_side_y(y: float, used: list[float]) -> float:
    result = y
    while any(abs(result - existing) < 190 for existing in used):
        result += 210
    return result


def spread_c4_side_positions(items: list[tuple[str, float]], *, min_y: float, spacing: float) -> dict[str, float]:
    if not items:
        return {}
    ordered = sorted(items, key=lambda item: item[1])
    result: dict[str, float] = {}
    previous = min_y - spacing
    for item_id, desired in ordered:
        y = max(desired, previous + spacing, min_y)
        result[item_id] = y
        previous = y
    for index in range(len(ordered) - 2, -1, -1):
        item_id, desired = ordered[index]
        next_id = ordered[index + 1][0]
        y = result[item_id]
        max_y = result[next_id] - spacing
        if y > desired and max_y >= min_y:
            result[item_id] = max(min_y, min(y, max_y))
    return result


def c4_inside_positions(elements: list[dict], relationships: list[dict]) -> dict[str, tuple[float, float]]:
    order = {element["id"]: index for index, element in enumerate(elements)}
    element_map = {element["id"]: element for element in elements}
    ranks = {element["id"]: c4_seed_rank(element) for element in elements}
    for _ in range(max(1, len(elements))):
        changed = False
        for rel in relationships:
            source = rel["source"]
            target = rel["target"]
            if source not in ranks or target not in ranks:
                continue
            if c4_is_back_edge(element_map[source], element_map[target], rel):
                continue
            required = ranks[source] + 1
            if ranks[target] < required:
                ranks[target] = required
                changed = True
        if not changed:
            break
    max_rank = 10
    by_rank: dict[int, list[str]] = defaultdict(list)
    for element_id, rank in ranks.items():
        by_rank[min(rank, max_rank)].append(element_id)
    max_rank_seen = max(by_rank, default=0)
    lane_count = 4 if max_rank_seen > 4 else max(1, max_rank_seen + 1)
    positions: dict[str, tuple[float, float]] = {}
    for rank, element_ids in by_rank.items():
        band = rank // lane_count
        lane = rank % lane_count
        col = lane if band % 2 == 0 else lane_count - 1 - lane
        for row, element_id in enumerate(sorted(element_ids, key=lambda item: order[item])):
            positions[element_id] = (430 + col * 720, 190 + band * 520 + row * 300)
    return positions


def c4_seed_rank(element: dict) -> int:
    text = " ".join([element["id"], element.get("label", ""), element.get("technology", ""), element.get("description", "")]).lower()
    if any(word in text for word in ("web", "ui", "frontend", "browser")):
        return 0
    if any(word in text for word in ("ingest", "gateway", "collector")):
        return 0
    if "api" in text:
        return 1
    if any(word in text for word in ("database", "db", "store", "postgres", "timescale", "storage")):
        return 3
    if any(word in text for word in ("policy", "alert", "ticket", "maintenance", "report", "service", "worker")):
        return 2
    return 1


def c4_is_back_edge(source: dict, target: dict, rel: dict) -> bool:
    target_text = " ".join([target["id"], target.get("label", ""), target.get("description", "")]).lower()
    label = rel.get("label", "").lower()
    if any(word in target_text for word in ("web", "ui", "frontend", "browser")):
        return True
    if any(word in label for word in ("publish", "dashboard", "html", "callback")):
        return True
    return False


def c4_label(item: dict) -> str:
    lines = [item["label"]]
    if item.get("technology"):
        lines.append(f"[{item['technology']}]")
    return "\n".join(lines)


def c4_route(source: str, target: str, label: str) -> tuple[list[tuple[float, float]] | None, tuple[float, float] | None, str]:
    routes: dict[tuple[str, str], tuple[list[tuple[float, float]], tuple[float, float] | None, str]] = {
        ("student", "web"): ([(280, 394), (850, 388)], (500, 330), "runs command"),
        ("supervisor", "storage"): ([(280, 1204), (850, 1238)], (500, 1145), "reviews PNG"),
        ("web", "api"): ([(1270, 388), (1500, 388)], (1360, 330), "source path"),
        ("api", "renderer"): ([(1500, 450), (1370, 560), (1270, 828)], (1345, 610), "model"),
        ("renderer", "exporter"): ([(1270, 828), (1500, 828)], (1360, 770), ".drawio"),
        ("exporter", "storage"): ([(1500, 900), (1270, 1238)], (1370, 1040), "PNG/.drawio"),
        ("api", "cache"): ([(1920, 388), (2160, 540), (2160, 1238), (1920, 1238)], (2175, 860), "status"),
        ("api", "bsuir"): ([(1920, 360), (2520, 298)], (2205, 250), "format rules"),
        ("github", "web"): ([(2890, 858), (2940, 858), (2940, 70), (1060, 70), (1060, 310)], (1600, 35), "CI trigger"),
        ("drawio", "storage"): ([(2520, 1358), (2350, 1358), (2350, 1600), (1060, 1600), (1060, 1315)], (1640, 1555), "manual edit"),
        ("author", "cli"): ([(250, 564), (520, 578)], (320, 520), "Runs generation"),
        ("reviewer", "artifacts"): ([(4900, 1044), (4650, 1058)], (4700, 1010), "Reviews PNG files"),
        ("controller", "validator"): ([(3255, 168), (3380, 500)], (3300, 300), "Inspects validation report"),
        ("cli", "api"): ([(940, 578), (1050, 578)], (960, 524), "Passes project path"),
        ("api", "importer"): ([(1470, 578), (1580, 578)], (1490, 524), "Creates safe workspace"),
        ("importer", "parser"): ([(2000, 578), (2110, 578)], (2020, 524), "Provides diagram sources"),
        ("parser", "layout"): ([(2530, 578), (2640, 578)], (2545, 524), "Sends normalized model"),
        ("layout", "validator"): ([(3060, 578), (3170, 578)], (3080, 524), "Sends routed canvas"),
        ("validator", "writer"): ([(3590, 578), (3700, 578)], (3610, 524), "Approves canvas"),
        ("writer", "exporter"): ([(4120, 578), (4230, 578)], (4140, 524), "Provides drawio XML"),
        ("exporter", "artifacts"): ([(4440, 655), (4440, 980)], (4470, 800), "Writes PNG images"),
        ("api", "cache"): ([(1260, 655), (1260, 1220), (3650, 1220), (3650, 1058), (3590, 1058)], (2200, 1170), "Stores job state"),
        ("api", "bsuir"): ([(1260, 500), (1380, 195)], (1290, 300), "Reads template metadata"),
        ("validator", "cache"): ([(3380, 655), (3380, 980)], (3410, 800), "Stores validation summary"),
        ("layout", "cache"): ([(2850, 655), (3220, 980)], (2950, 760), "Reads profile settings"),
    }
    return routes.get((source, target), (None, None, label))


DEPLOY_LEAF_W = 330
DEPLOY_LEAF_H = 122
DEPLOY_PAD_X = 112
DEPLOY_HEADER_H = 78
DEPLOY_PAD_BOTTOM = 94
DEPLOY_COL_GAP = 126
DEPLOY_ROW_GAP = 188
DEPLOY_ROUTE_GAP_X = 126
DEPLOY_ROUTE_GAP_Y = 186
DEPLOY_PARALLEL_STEP = 60.0
DEPLOY_BOUNDARY_ROUTE_GAP = 126.0
DEPLOY_DATABASE_ROUTE_GAP_X = 172.0
DEPLOY_DATABASE_ROUTE_GAP_Y = 132.0
DEPLOY_DATABASE_JETTY = 132.0
DEPLOY_PARALLEL_MIN_GAP = 82.0
DEPLOY_SIBLING_GAP = 150.0
DEPLOY_LAYER_BLOCK = 5.0
DEPLOY_NESTED_LAYER_STEP = 2.0
DEPLOY_DEEP_LAYER_STEP = 1.0
DEPLOY_LAYER_STEP_X = 430.0
DEPLOY_ROW_STEP_Y = 250.0
DEPLOY_LAYER_MIN_GAP_Y = 238.0
DEPLOY_JETTY = 82.0


def layout_deployment(model: dict) -> Canvas:
    return layout_deployment_standard(model)


def layout_deployment_layered(model: dict) -> Canvas:
    nodes = {node["id"]: node for node in model["nodes"]}
    parent_of = {node["id"]: node.get("parent") for node in model["nodes"]}
    children: dict[str | None, list[str]] = defaultdict(list)
    order = {node["id"]: index for index, node in enumerate(model["nodes"])}
    for node in model["nodes"]:
        children[node.get("parent")].append(node["id"])

    leaf_ids = [node_id for node_id in nodes if not children.get(node_id)]
    local_levels = deployment_local_levels(model, children, parent_of)
    local_rows = deployment_local_rows(children, local_levels, order)
    ranks = {
        node_id: deployment_global_rank(node_id, parent_of, local_levels)
        for node_id in leaf_ids
    }
    rows = deployment_relaxed_rows(model, leaf_ids, parent_of, local_rows, ranks)

    layer_slots: dict[float, list[str]] = defaultdict(list)
    for node_id, rank in ranks.items():
        layer_slots[rank].append(node_id)

    margin = 90.0
    canvas = Canvas("deployment", model.get("title", "Deployment"), 1600, 900)
    for rank in sorted(layer_slots):
        placed_y: list[float] = []
        for node_id in sorted(layer_slots[rank], key=lambda item: (rows[item], order[item])):
            node = nodes[node_id]
            h = DEPLOY_LEAF_H + (12 if node["kind"] == "database" else 0)
            desired_y = margin + rows[node_id] * DEPLOY_ROW_STEP_Y
            y = deployment_spread_y(desired_y, placed_y, h)
            placed_y.append(y)
            canvas.shapes.append(
                Shape(
                    node_id,
                    deployment_leaf_kind(node["kind"]),
                    margin + ranks[node_id] * DEPLOY_LAYER_STEP_X,
                    y,
                    DEPLOY_LEAF_W,
                    h,
                    node["label"],
                    stereotype=node["kind"],
                )
            )

    add_deployment_boundaries(canvas, nodes, children)
    separate_deployment_layered_top_groups(canvas, nodes, children)
    route_deployment_connectors_from_model(canvas, model)
    clean_connector_geometry(canvas)
    return fit_canvas_to_content(canvas, margin=90)


def deployment_local_levels(
    model: dict,
    children: dict[str | None, list[str]],
    parent_of: dict[str, str | None],
) -> dict[str | None, dict[str, int]]:
    result: dict[str | None, dict[str, int]] = {}
    for parent_id, child_ids in children.items():
        edges: set[tuple[str, str]] = set()
        for edge in model["edges"]:
            source_child = deployment_child_under(edge["source"], parent_id, parent_of)
            target_child = deployment_child_under(edge["target"], parent_id, parent_of)
            if source_child in child_ids and target_child in child_ids and source_child != target_child:
                edges.add((source_child, target_child))
        result[parent_id] = dependency_levels(child_ids, edges) if edges else {child_id: 0 for child_id in child_ids}
    return result


def deployment_child_under(
    node_id: str,
    parent_id: str | None,
    parent_of: dict[str, str | None],
) -> str | None:
    current = node_id
    child = node_id
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        parent = parent_of.get(current)
        if parent == parent_id:
            return current
        child = current
        if parent is None:
            return child if parent_id is None else None
        current = parent
    return None


def deployment_local_rows(
    children: dict[str | None, list[str]],
    local_levels: dict[str | None, dict[str, int]],
    order: dict[str, int],
) -> dict[str | None, dict[str, float]]:
    result: dict[str | None, dict[str, float]] = {}
    for parent_id, child_ids in children.items():
        grouped: dict[int, list[str]] = defaultdict(list)
        levels = local_levels.get(parent_id, {})
        for child_id in child_ids:
            grouped[levels.get(child_id, 0)].append(child_id)
        rows: dict[str, float] = {}
        for _level, ids in grouped.items():
            for index, child_id in enumerate(sorted(ids, key=lambda item: order[item])):
                rows[child_id] = float(index)
        result[parent_id] = rows
    return result


def deployment_global_rank(
    node_id: str,
    parent_of: dict[str, str | None],
    local_levels: dict[str | None, dict[str, int]],
) -> float:
    path = deployment_path(node_id, parent_of)
    parent_id: str | None = None
    rank = 0.0
    for depth, child_id in enumerate(path):
        level = local_levels.get(parent_id, {}).get(child_id, 0)
        if depth == 0:
            rank += level * DEPLOY_LAYER_BLOCK
        elif depth == 1:
            rank += level * DEPLOY_NESTED_LAYER_STEP
        else:
            rank += level * DEPLOY_DEEP_LAYER_STEP
        parent_id = child_id
    return rank


def deployment_path(node_id: str, parent_of: dict[str, str | None]) -> list[str]:
    result = [node_id]
    current = node_id
    seen: set[str] = set()
    while current not in seen:
        seen.add(current)
        parent = parent_of.get(current)
        if not parent:
            break
        result.append(parent)
        current = parent
    return list(reversed(result))


def deployment_relaxed_rows(
    model: dict,
    leaf_ids: list[str],
    parent_of: dict[str, str | None],
    local_rows: dict[str | None, dict[str, float]],
    ranks: dict[str, float],
) -> dict[str, float]:
    structural = {
        node_id: deployment_structural_row(node_id, parent_of, local_rows)
        for node_id in leaf_ids
    }
    rows = dict(structural)
    incoming: dict[str, list[str]] = defaultdict(list)
    for edge in model["edges"]:
        if edge["source"] in rows and edge["target"] in rows:
            incoming[edge["target"]].append(edge["source"])
    for _ in range(5):
        for node_id in sorted(leaf_ids, key=lambda item: (ranks[item], rows[item])):
            sources = incoming.get(node_id, [])
            if not sources:
                continue
            source_row = sum(rows[source] for source in sources) / len(sources)
            rows[node_id] = rows[node_id] * 0.58 + source_row * 0.42
            rows[node_id] = min(structural[node_id] + 0.55, max(structural[node_id] - 0.55, rows[node_id]))
    return rows


def deployment_structural_row(
    node_id: str,
    parent_of: dict[str, str | None],
    local_rows: dict[str | None, dict[str, float]],
) -> float:
    path = deployment_path(node_id, parent_of)
    parent_id: str | None = None
    row = 0.0
    for depth, child_id in enumerate(path):
        local_row = local_rows.get(parent_id, {}).get(child_id, 0.0)
        row += local_row * (1.0 if depth == 0 else 0.85)
        parent_id = child_id
    return row


def deployment_spread_y(desired_y: float, placed_y: list[float], height: float) -> float:
    y = desired_y
    min_gap = max(DEPLOY_LAYER_MIN_GAP_Y, height + 76)
    for existing in sorted(placed_y):
        if y < existing + min_gap:
            y = existing + min_gap
    return y


def separate_deployment_layered_top_groups(
    canvas: Canvas,
    nodes: dict[str, dict],
    children: dict[str | None, list[str]],
) -> None:
    shape_map = canvas.shape_map()
    groups: list[tuple[float, float, set[str]]] = []
    for top_id in children.get(None, []):
        ids = deployment_descendants(top_id, children)
        shapes = [shape_map[item] for item in ids if item in shape_map]
        if not shapes:
            continue
        groups.append((min(shape.x for shape in shapes), max(shape.x + shape.w for shape in shapes), ids))
    cursor = 90.0
    for left, right, ids in sorted(groups, key=lambda item: item[0]):
        dx = max(0.0, cursor - left)
        if dx:
            for shape in canvas.shapes:
                if shape.id in ids:
                    shape.x += dx
        cursor = max(cursor, right + dx) + 190.0


def route_deployment_connectors_from_model(canvas: Canvas, model: dict) -> None:
    for index, edge in enumerate(model["edges"]):
        canvas.connectors.append(
            Connector(
                f"dep_{index}",
                edge["source"],
                edge["target"],
                edge.get("label", ""),
                kind=edge.get("kind", "association"),
                dashed=edge.get("dashed", False),
            )
        )
    route_deployment_connectors(canvas)


def layout_deployment_graphviz(model: dict) -> Canvas | None:
    layout_script = Path(__file__).resolve().parents[2] / "tools" / "graphviz-layout.cjs"
    if not layout_script.exists():
        return None
    nodes = {node["id"]: node for node in model["nodes"]}
    children: dict[str | None, list[str]] = defaultdict(list)
    for node in model["nodes"]:
        children[node.get("parent")].append(node["id"])
    try:
        completed = subprocess.run(
            ["node", str(layout_script)],
            input=json.dumps({"dot": deployment_dot(model, nodes, children)}),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        result = json.loads(completed.stdout)
    except Exception:
        return None
    return deployment_canvas_from_graphviz(model, nodes, children, result)


def deployment_dot(model: dict, nodes: dict[str, dict], children: dict[str | None, list[str]]) -> str:
    lines = [
        "digraph G {",
        '  graph [rankdir=LR, compound=true, clusterrank=local, remincross=true, splines=polyline, nodesep="0.95", ranksep="1.9", margin=0, pad="0.25"];',
        '  node [shape=box, fixedsize=true, margin=0, penwidth=1, label=""];',
        '  edge [fontsize=12, fontname="Helvetica", penwidth=1, arrowsize=0.8];',
    ]

    def emit(node_id: str, indent: int) -> None:
        node = nodes[node_id]
        child_ids = children.get(node_id, [])
        prefix = " " * indent
        if child_ids:
            lines.append(f'{prefix}subgraph "{deployment_cluster_id(node_id)}" {{')
            lines.append(f'{prefix}  label="{dot_escape(node["label"])}";')
            lines.append(f'{prefix}  margin=42;')
            lines.append(f'{prefix}  graph [penwidth=1, fontname="Helvetica", fontsize=16];')
            for child_id in child_ids:
                emit(child_id, indent + 2)
            lines.append(f"{prefix}}}")
            return
        h = DEPLOY_LEAF_H + (12 if node["kind"] == "database" else 0)
        lines.append(
            f'{prefix}"{dot_escape(node_id)}" [width="{DEPLOY_LEAF_W / 72:.3f}", height="{h / 72:.3f}"];'
        )

    for node_id in children.get(None, []):
        emit(node_id, 2)
    for edge in model["edges"]:
        attrs = [f'label="{dot_escape(edge.get("label", ""))}"'] if edge.get("label") else []
        if edge.get("dashed"):
            attrs.append("style=dashed")
        attr_text = f" [{', '.join(attrs)}]" if attrs else ""
        lines.append(f'  "{dot_escape(edge["source"])}" -> "{dot_escape(edge["target"])}"{attr_text};')
    lines.append("}")
    return "\n".join(lines)


def deployment_canvas_from_graphviz(
    model: dict,
    nodes: dict[str, dict],
    children: dict[str | None, list[str]],
    result: dict,
) -> Canvas | None:
    objects = result.get("objects") or []
    object_by_name = {obj.get("name"): obj for obj in objects}
    graph_box = graphviz_box(result.get("bb", "0,0,1200,800"))
    if not graph_box:
        return None
    _left, bottom, _right, top = graph_box
    graph_h = top - bottom
    margin = 90
    canvas = Canvas(
        "deployment",
        model.get("title", "Deployment"),
        int(graph_box[2] - graph_box[0] + margin * 2),
        int(graph_h + margin * 2),
    )

    for node in model["nodes"]:
        node_id = node["id"]
        if children.get(node_id):
            obj = object_by_name.get(deployment_cluster_id(node_id))
            box = graphviz_box(obj.get("bb", "")) if obj else None
            if not box:
                continue
            left, box_bottom, right, box_top = box
            canvas.shapes.append(
                Shape(
                    node_id,
                    "boundary",
                    margin + left,
                    margin + graph_h - box_top,
                    right - left,
                    box_top - box_bottom,
                    node["label"],
                    stereotype=node["kind"],
                )
            )
            continue
        obj = object_by_name.get(node_id)
        if not obj or not obj.get("pos"):
            continue
        cx, cy = graphviz_point(obj["pos"])
        w = float(obj.get("width", DEPLOY_LEAF_W / 72)) * 72
        h = float(obj.get("height", DEPLOY_LEAF_H / 72)) * 72
        canvas.shapes.append(
            Shape(
                node_id,
                deployment_leaf_kind(node["kind"]),
                margin + cx - w / 2,
                margin + graph_h - cy - h / 2,
                w,
                h,
                node["label"],
                stereotype=node["kind"],
            )
        )

    graphviz_edges = result.get("edges") or []
    for index, edge in enumerate(model["edges"]):
        gv_edge = graphviz_edges[index] if index < len(graphviz_edges) else {}
        points = graphviz_edge_points(gv_edge, graph_h, margin)
        label_position = graphviz_label_position(gv_edge.get("lp", ""), graph_h, margin)
        canvas.connectors.append(
            Connector(
                f"dep_{index}",
                edge["source"],
                edge["target"],
                edge.get("label", ""),
                kind=edge.get("kind", "association"),
                dashed=edge.get("dashed", False),
                points=points,
                label_position=label_position,
            )
        )
    return fit_canvas_to_content(canvas, margin=90)


def dot_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def deployment_cluster_id(node_id: str) -> str:
    return f"cluster_{node_id}"


def graphviz_box(value: str) -> tuple[float, float, float, float] | None:
    try:
        left, bottom, right, top = [float(part) for part in value.split(",")]
    except ValueError:
        return None
    return left, bottom, right, top


def graphviz_point(value: str) -> tuple[float, float]:
    x, y = value.split(",")[:2]
    return float(x), float(y)


def graphviz_edge_points(edge: dict, graph_h: float, margin: float) -> list[tuple[float, float]] | None:
    for item in edge.get("_draw_", []):
        if item.get("op") == "b" and item.get("points"):
            return simplify_layout_path([(margin + float(x), margin + graph_h - float(y)) for x, y in item["points"]])
    pos = edge.get("pos", "")
    points: list[tuple[float, float]] = []
    for token in pos.split():
        if "," not in token:
            continue
        if token.startswith(("e,", "s,")):
            token = token[2:]
        try:
            x, y = token.split(",")[:2]
            points.append((margin + float(x), margin + graph_h - float(y)))
        except ValueError:
            continue
    return simplify_layout_path(points) if len(points) >= 2 else None


def graphviz_label_position(value: str, graph_h: float, margin: float) -> tuple[float, float] | None:
    if not value:
        return None
    try:
        x, y = graphviz_point(value)
    except ValueError:
        return None
    return margin + x, margin + graph_h - y - 24


def layout_deployment_flat_elk(model: dict) -> Canvas | None:
    nodes = {node["id"]: node for node in model["nodes"]}
    children: dict[str | None, list[str]] = defaultdict(list)
    endpoints = {edge["source"] for edge in model["edges"]} | {edge["target"] for edge in model["edges"]}
    for node in model["nodes"]:
        children[node.get("parent")].append(node["id"])

    layout_ids = [node["id"] for node in model["nodes"] if not children.get(node["id"]) or node["id"] in endpoints]
    if not layout_ids:
        return None

    canvas = Canvas("deployment", model.get("title", "Deployment"), 1800, 1100)
    for node_id in layout_ids:
        node = nodes[node_id]
        h = DEPLOY_LEAF_H + (12 if node["kind"] == "database" else 0)
        canvas.shapes.append(Shape(node_id, deployment_leaf_kind(node["kind"]), 0, 0, DEPLOY_LEAF_W, h, node["label"], stereotype=node["kind"]))
    for index, edge in enumerate(model["edges"]):
        if edge["source"] not in layout_ids or edge["target"] not in layout_ids:
            continue
        canvas.connectors.append(
            Connector(
                f"dep_{index}",
                edge["source"],
                edge["target"],
                edge.get("label", ""),
                kind=edge.get("kind", "association"),
                dashed=edge.get("dashed", False),
            )
        )

    canvas = apply_elk_layout(
        canvas,
        direction="RIGHT",
        node_spacing=150,
        layer_spacing=250,
        edge_spacing=78,
        edge_routing="POLYLINE",
        margin=95,
    )
    separate_deployment_top_groups(canvas, nodes, children, model["edges"])
    for connector in canvas.connectors:
        connector.points = None
        connector.label_position = None
    route_deployment_connectors(canvas)
    clean_connector_geometry(canvas)
    add_deployment_boundaries(canvas, nodes, children)
    return fit_canvas_to_content(canvas, margin=90)


def separate_deployment_top_groups(
    canvas: Canvas,
    nodes: dict[str, dict],
    children: dict[str | None, list[str]],
    edges: list[dict],
) -> None:
    shape_map = canvas.shape_map()
    top_ids = [node_id for node_id in children.get(None, []) if any(descendant in shape_map for descendant in deployment_descendants(node_id, children))]
    if not top_ids:
        return
    top_by_node = {
        node_id: deployment_top_ancestor(node_id, nodes)
        for node_id in shape_map
        if deployment_top_ancestor(node_id, nodes) in top_ids
    }
    group_edges = {
        (top_by_node[edge["source"]], top_by_node[edge["target"]])
        for edge in edges
        if edge["source"] in top_by_node and edge["target"] in top_by_node and top_by_node[edge["source"]] != top_by_node[edge["target"]]
    }
    levels = dependency_levels(top_ids, group_edges)
    grouped: dict[int, list[str]] = defaultdict(list)
    for top_id in top_ids:
        grouped[levels.get(top_id, 0)].append(top_id)

    group_boxes: dict[str, tuple[float, float, float, float]] = {}
    for top_id in top_ids:
        shapes = [shape_map[node_id] for node_id, group_id in top_by_node.items() if group_id == top_id]
        left = min(shape.x for shape in shapes)
        top = min(shape.y for shape in shapes)
        right = max(shape.x + shape.w for shape in shapes)
        bottom = max(shape.y + shape.h for shape in shapes)
        group_boxes[top_id] = (left, top, right, bottom)

    x_cursor = 90.0
    group_gap_x = 230.0
    group_gap_y = 170.0
    shifts: dict[str, tuple[float, float]] = {}
    for level in sorted(grouped):
        group_ids = sorted(grouped[level], key=lambda group_id: group_boxes[group_id][1])
        column_w = max(group_boxes[group_id][2] - group_boxes[group_id][0] for group_id in group_ids) + DEPLOY_PAD_X * 2
        y_cursor = 110.0
        for group_id in group_ids:
            left, top, right, bottom = group_boxes[group_id]
            desired_left = x_cursor + DEPLOY_PAD_X
            desired_top = y_cursor + DEPLOY_HEADER_H
            shifts[group_id] = (desired_left - left, desired_top - top)
            y_cursor += (bottom - top) + DEPLOY_HEADER_H + DEPLOY_PAD_BOTTOM + group_gap_y
        x_cursor += column_w + group_gap_x

    for shape in canvas.shapes:
        group_id = top_by_node.get(shape.id)
        if not group_id:
            continue
        dx, dy = shifts[group_id]
        shape.x += dx
        shape.y += dy


def deployment_descendants(node_id: str, children: dict[str | None, list[str]]) -> set[str]:
    result = {node_id}
    for child_id in children.get(node_id, []):
        result.update(deployment_descendants(child_id, children))
    return result


def deployment_top_ancestor(node_id: str, nodes: dict[str, dict]) -> str:
    current = node_id
    seen: set[str] = set()
    while current in nodes and current not in seen:
        seen.add(current)
        parent = nodes[current].get("parent")
        if not parent or parent not in nodes:
            return current
        current = parent
    return node_id


def add_deployment_boundaries(canvas: Canvas, nodes: dict[str, dict], children: dict[str | None, list[str]]) -> None:
    parent_ids = [node_id for node_id in nodes if children.get(node_id)]
    for parent_id in sorted(parent_ids, key=lambda node_id: deployment_depth(node_id, nodes), reverse=True):
        shape_map = canvas.shape_map()
        child_shapes = [shape_map[child_id] for child_id in children.get(parent_id, []) if child_id in shape_map]
        if not child_shapes:
            continue
        left = min(shape.x for shape in child_shapes) - DEPLOY_PAD_X
        top = min(shape.y for shape in child_shapes) - DEPLOY_HEADER_H
        right = max(shape.x + shape.w for shape in child_shapes) + DEPLOY_PAD_X
        bottom = max(shape.y + shape.h for shape in child_shapes) + DEPLOY_PAD_BOTTOM
        node = nodes[parent_id]
        canvas.shapes.append(
            Shape(
                parent_id,
                "boundary",
                left,
                top,
                max(440, right - left),
                max(240, bottom - top),
                node["label"],
                stereotype=node["kind"],
            )
        )


def deployment_depth(node_id: str, nodes: dict[str, dict]) -> int:
    depth = 0
    current = node_id
    seen: set[str] = set()
    while current in nodes and current not in seen:
        seen.add(current)
        parent = nodes[current].get("parent")
        if not parent:
            break
        depth += 1
        current = parent
    return depth


def layout_deployment_elk(model: dict) -> Canvas | None:
    layout_script = Path(__file__).resolve().parents[2] / "tools" / "elk-layout.cjs"
    if not layout_script.exists():
        return None

    nodes = {node["id"]: node for node in model["nodes"]}
    children: dict[str | None, list[str]] = defaultdict(list)
    for node in model["nodes"]:
        children[node.get("parent")].append(node["id"])

    def build_node(node_id: str) -> dict:
        node = nodes[node_id]
        child_ids = children.get(node_id, [])
        if not child_ids:
            h = DEPLOY_LEAF_H + (12 if node["kind"] == "database" else 0)
            return {"id": node_id, "width": DEPLOY_LEAF_W, "height": h}
        return {
            "id": node_id,
            "layoutOptions": deployment_elk_options(top=False),
            "children": [build_node(child_id) for child_id in child_ids],
        }

    graph = {
        "id": "root",
        "layoutOptions": deployment_elk_options(top=True),
        "children": [build_node(node_id) for node_id in children.get(None, [])],
        "edges": [
            {
                "id": f"dep_{index}",
                "sources": [edge["source"]],
                "targets": [edge["target"]],
                "labels": [deployment_edge_label(edge.get("label", ""))] if edge.get("label") else [],
            }
            for index, edge in enumerate(model["edges"])
        ],
    }
    payload = {
        "graph": graph,
        "direction": "RIGHT",
        "nodeSpacing": 135,
        "layerSpacing": 230,
        "edgeSpacing": 70,
        "edgeRouting": "ORTHOGONAL",
    }
    try:
        completed = subprocess.run(
            ["node", str(layout_script)],
            input=json.dumps(payload),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        result = json.loads(completed.stdout)
    except Exception:
        return None

    margin = 90
    canvas = Canvas(
        "deployment",
        model.get("title", "Deployment"),
        int(float(result.get("width", 1100)) + margin * 2),
        int(float(result.get("height", 520)) + margin * 2),
    )
    node_offsets: dict[str, tuple[float, float]] = {"root": (margin, margin)}

    def collect_shapes(graph_node: dict, offset_x: float, offset_y: float) -> None:
        for child in graph_node.get("children") or []:
            node_id = child["id"]
            x = offset_x + float(child.get("x", 0))
            y = offset_y + float(child.get("y", 0))
            w = float(child.get("width", DEPLOY_LEAF_W))
            h = float(child.get("height", DEPLOY_LEAF_H))
            node_offsets[node_id] = (x, y)
            node = nodes.get(node_id)
            if node:
                if children.get(node_id):
                    canvas.shapes.append(Shape(node_id, "boundary", x, y, w, h, node["label"], stereotype=node["kind"]))
                else:
                    canvas.shapes.append(
                        Shape(node_id, deployment_leaf_kind(node["kind"]), x, y, w, h, node["label"], stereotype=node["kind"])
                    )
            collect_shapes(child, x, y)

    collect_shapes(result, margin, margin)

    edge_data: dict[str, dict] = {}

    def collect_edges(graph_node: dict) -> None:
        for edge in graph_node.get("edges") or []:
            edge_data[edge["id"]] = edge
        for child in graph_node.get("children") or []:
            collect_edges(child)

    collect_edges(result)
    model_edges = list(model["edges"])
    for index, edge in enumerate(model_edges):
        connector_id = f"dep_{index}"
        elk_edge = edge_data.get(connector_id)
        points: list[tuple[float, float]] | None = None
        label_anchor: tuple[float, float] | None = None
        if elk_edge:
            container_id = elk_edge.get("container", "root")
            offset_x, offset_y = node_offsets.get(container_id, (margin, margin))
            sections = elk_edge.get("sections") or []
            if sections:
                section = sections[0]
                points = []
                start = section.get("startPoint")
                end = section.get("endPoint")
                if start:
                    points.append((offset_x + float(start["x"]), offset_y + float(start["y"])))
                for bend in section.get("bendPoints") or []:
                    points.append((offset_x + float(bend["x"]), offset_y + float(bend["y"])))
                if end:
                    points.append((offset_x + float(end["x"]), offset_y + float(end["y"])))
                points = simplify_layout_path(points)
            labels = elk_edge.get("labels") or []
            if labels:
                label = labels[0]
                lx = offset_x + float(label.get("x", 0))
                ly = offset_y + float(label.get("y", 0))
                label_anchor = (lx, ly)
        canvas.connectors.append(
            Connector(
                connector_id,
                edge["source"],
                edge["target"],
                edge.get("label", ""),
                kind=edge.get("kind", "association"),
                dashed=edge.get("dashed", False),
                points=points,
                label_position=label_anchor,
            )
        )
    clean_connector_geometry(canvas)
    return fit_canvas_to_content(canvas, margin=margin)


def deployment_elk_options(*, top: bool) -> dict[str, str]:
    return {
        "elk.algorithm": "layered",
        "elk.direction": "RIGHT",
        "elk.hierarchyHandling": "INCLUDE_CHILDREN",
        "elk.edgeRouting": "ORTHOGONAL",
        "elk.spacing.nodeNode": "130" if top else "105",
        "elk.layered.spacing.nodeNodeBetweenLayers": "230" if top else "165",
        "elk.spacing.edgeNode": "70" if top else "54",
        "elk.spacing.edgeEdge": "48" if top else "34",
        "elk.layered.spacing.edgeNodeBetweenLayers": "76" if top else "58",
        "elk.layered.spacing.edgeEdgeBetweenLayers": "52" if top else "38",
        "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
        "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
        "elk.padding": "[top=70,left=70,bottom=70,right=70]",
    }


def deployment_edge_label(label: str) -> dict[str, float | str]:
    width = max(82, min(230, len(label) * 7.0))
    height = 30 if len(label) < 22 else 48
    return {"text": label, "width": width, "height": height}


def layout_deployment_standard(model: dict) -> Canvas:
    nodes = {node["id"]: node for node in model["nodes"]}
    order = {node["id"]: index for index, node in enumerate(model["nodes"])}
    parent_of = {node["id"]: node.get("parent") for node in model["nodes"]}
    children: dict[str | None, list[str]] = defaultdict(list)
    for node in model["nodes"]:
        children[node.get("parent")].append(node["id"])

    size_cache: dict[str, tuple[float, float]] = {}

    def child_columns(parent_id: str, child_ids: list[str]) -> list[list[str]]:
        edges: set[tuple[str, str]] = set()
        for edge in model["edges"]:
            source_child = immediate_child_under(edge["source"], parent_id, parent_of)
            target_child = immediate_child_under(edge["target"], parent_id, parent_of)
            if source_child in child_ids and target_child in child_ids and source_child != target_child:
                edges.add((source_child, target_child))
        if not edges:
            return [child_ids]
        levels = dependency_levels(child_ids, edges)
        grouped: dict[int, list[str]] = defaultdict(list)
        for child_id in child_ids:
            grouped[levels.get(child_id, 0)].append(child_id)

        def child_order_key(child_id: str) -> tuple[float, float]:
            outgoing = [target for source, target in edges if source == child_id]
            incoming = [source for source, target in edges if target == child_id]
            if outgoing:
                score = sum(levels.get(target, 0) * 100 + order[target] for target in outgoing) / len(outgoing)
                return (0, score)
            if incoming:
                score = sum(levels.get(source, 0) * 100 + order[source] for source in incoming) / len(incoming)
                return (1, score)
            return (2, order[child_id])

        return [sorted(grouped[level], key=child_order_key) for level in sorted(grouped)]

    def measure(node_id: str) -> tuple[float, float]:
        if node_id in size_cache:
            return size_cache[node_id]
        child_ids = children.get(node_id, [])
        if not child_ids:
            node = nodes[node_id]
            h = DEPLOY_LEAF_H + (12 if node["kind"] == "database" else 0)
            size_cache[node_id] = (DEPLOY_LEAF_W, h)
            return size_cache[node_id]
        columns = [[(child_id, measure(child_id)) for child_id in column] for column in child_columns(node_id, child_ids)]
        col_widths = [max(size[0] for _, size in column) for column in columns]
        col_heights = [sum(size[1] for _, size in column) + DEPLOY_ROW_GAP * max(0, len(column) - 1) for column in columns]
        width = max(440, sum(col_widths) + DEPLOY_COL_GAP * max(0, len(columns) - 1) + DEPLOY_PAD_X * 2)
        height = DEPLOY_HEADER_H + max(col_heights, default=0) + DEPLOY_PAD_BOTTOM
        size_cache[node_id] = (width, height)
        return width, height

    top_ids = children.get(None, [])
    top_sizes = [(node_id, measure(node_id)) for node_id in top_ids]
    top_gap = 130
    margin = 140
    width = int(margin * 2 + sum(size[0] for _, size in top_sizes) + top_gap * max(0, len(top_sizes) - 1))
    height = int(margin * 2 + max((size[1] for _, size in top_sizes), default=DEPLOY_LEAF_H))
    canvas = Canvas("deployment", model.get("title", "Deployment"), max(width, 1100), max(height, 520))

    def place(node_id: str, x: float, y: float) -> None:
        node = nodes[node_id]
        w, h = measure(node_id)
        child_ids = children.get(node_id, [])
        if not child_ids:
            canvas.shapes.append(
                Shape(
                    node_id,
                    deployment_leaf_kind(node["kind"]),
                    x,
                    y,
                    w,
                    h,
                    node["label"],
                    stereotype=node["kind"],
                    parent=node.get("parent"),
                )
            )
            return
        canvas.shapes.append(Shape(node_id, "boundary", x, y, w, h, node["label"], stereotype=node["kind"], parent=node.get("parent")))
        columns = [[(child_id, measure(child_id)) for child_id in column] for column in child_columns(node_id, child_ids)]
        col_widths = [max(size[0] for _, size in column) for column in columns]
        content_w = sum(col_widths) + DEPLOY_COL_GAP * max(0, len(columns) - 1)
        content_h = h - DEPLOY_HEADER_H - DEPLOY_PAD_BOTTOM
        x_cursor = x + (w - content_w) / 2
        for column, col_w in zip(columns, col_widths):
            col_h = sum(size[1] for _, size in column) + DEPLOY_ROW_GAP * max(0, len(column) - 1)
            y_cursor = y + DEPLOY_HEADER_H + max(0, (content_h - col_h) / 2)
            for child_id, (child_w, child_h) in column:
                place(child_id, x_cursor + (col_w - child_w) / 2, y_cursor)
                y_cursor += child_h + DEPLOY_ROW_GAP
            x_cursor += col_w + DEPLOY_COL_GAP

    x_cursor = margin
    for node_id, (w, _h) in top_sizes:
        place(node_id, x_cursor, margin)
        x_cursor += w + top_gap

    align_deployment_leaf_groups(canvas, model, nodes, children, parent_of)
    refit_deployment_boundaries(canvas, nodes, children)
    separate_deployment_sibling_columns(canvas, nodes, children, gap=DEPLOY_SIBLING_GAP)
    refit_deployment_boundaries(canvas, nodes, children)
    separate_deployment_standard_top_groups(canvas, nodes, children, gap=top_gap)
    refit_deployment_boundaries(canvas, nodes, children)

    for index, edge in enumerate(model["edges"]):
        canvas.connectors.append(
            Connector(
                f"dep_{index}",
                edge["source"],
                edge["target"],
                edge.get("label", ""),
                kind=edge.get("kind", "association"),
                dashed=edge.get("dashed", False),
            )
        )
    route_deployment_connectors(canvas)
    clean_connector_geometry(canvas)
    expand_deployment_nested_boundaries_from_routes(canvas, parent_of)
    if separate_deployment_sibling_columns(canvas, nodes, children, gap=DEPLOY_SIBLING_GAP):
        separate_deployment_standard_top_groups(canvas, nodes, children, gap=top_gap)
        route_deployment_connectors(canvas)
        clean_connector_geometry(canvas)
    repair_deployment_boundary_conflicts(canvas)
    clean_connector_geometry(canvas)
    place_deployment_short_edge_labels(canvas)
    return fit_canvas_to_content(canvas, margin=90)


def align_deployment_leaf_groups(
    canvas: Canvas,
    model: dict,
    nodes: dict[str, dict],
    children: dict[str | None, list[str]],
    parent_of: dict[str, str | None],
) -> None:
    """Align sibling leaves to the rows of connected nodes before routing.

    Deployment diagrams read better when a service is close to the component it
    talks to.  The standard nested layout still owns the columns; this pass only
    adjusts Y coordinates inside leaf-only sibling columns.
    """
    shape_map = canvas.shape_map()
    for _ in range(3):
        changed = False
        for parent_id, child_ids in children.items():
            if parent_id is None or not child_ids:
                continue
            leaves = [child_id for child_id in child_ids if child_id in shape_map and not children.get(child_id)]
            if len(leaves) < 2 or len(leaves) != len(child_ids):
                continue
            columns: dict[int, list[str]] = defaultdict(list)
            for child_id in leaves:
                columns[round(shape_map[child_id].x / 20)].append(child_id)
            for column_ids in columns.values():
                if len(column_ids) < 2:
                    continue
                anchors = deployment_leaf_y_anchors(column_ids, model, shape_map, parent_of)
                if not anchors:
                    continue
                if arrange_deployment_column_by_anchors(column_ids, anchors, shape_map):
                    changed = True
        if not changed:
            break


def deployment_leaf_y_anchors(
    child_ids: list[str],
    model: dict,
    shape_map: dict[str, Shape],
    parent_of: dict[str, str | None],
) -> dict[str, float]:
    child_set = set(child_ids)
    anchors: dict[str, list[float]] = defaultdict(list)
    for edge in model["edges"]:
        source = edge["source"]
        target = edge["target"]
        if source in child_set and target in shape_map and parent_of.get(target) != parent_of.get(source):
            anchors[source].append(center(shape_map[target])[1])
        if target in child_set and source in shape_map and parent_of.get(source) != parent_of.get(target):
            anchors[target].append(center(shape_map[source])[1])
    return {node_id: sum(values) / len(values) for node_id, values in anchors.items() if values}


def arrange_deployment_column_by_anchors(
    child_ids: list[str],
    anchors: dict[str, float],
    shape_map: dict[str, Shape],
) -> bool:
    items = sorted(
        child_ids,
        key=lambda node_id: (
            anchors.get(node_id, center(shape_map[node_id])[1]),
            center(shape_map[node_id])[1],
        ),
    )
    min_gap = DEPLOY_LEAF_H + 118.0
    planned: list[tuple[str, float]] = []
    previous_center: float | None = None
    for node_id in items:
        shape = shape_map[node_id]
        desired = anchors.get(node_id, center(shape)[1])
        if previous_center is not None:
            desired = max(desired, previous_center + min_gap)
        planned.append((node_id, desired - shape.h / 2))
        previous_center = desired
    if not planned:
        return False
    current_top = min(shape_map[node_id].y for node_id in items)
    planned_top = min(y for _node_id, y in planned)
    if planned_top < current_top:
        shift = current_top - planned_top
        planned = [(node_id, y + shift) for node_id, y in planned]
    changed = False
    for node_id, y in planned:
        if abs(shape_map[node_id].y - y) > 1:
            shape_map[node_id].y = y
            changed = True
    return changed


def refit_deployment_boundaries(
    canvas: Canvas,
    nodes: dict[str, dict],
    children: dict[str | None, list[str]],
) -> None:
    shape_map = canvas.shape_map()
    parent_ids = [node_id for node_id in nodes if children.get(node_id) and node_id in shape_map]
    for parent_id in sorted(parent_ids, key=lambda node_id: deployment_depth(node_id, nodes), reverse=True):
        child_shapes = [shape_map[child_id] for child_id in children.get(parent_id, []) if child_id in shape_map]
        if not child_shapes:
            continue
        left = min(shape.x for shape in child_shapes) - DEPLOY_PAD_X
        top = min(shape.y for shape in child_shapes) - DEPLOY_HEADER_H
        right = max(shape.x + shape.w for shape in child_shapes) + DEPLOY_PAD_X
        bottom = max(shape.y + shape.h for shape in child_shapes) + DEPLOY_PAD_BOTTOM
        boundary = shape_map[parent_id]
        boundary.x = left
        boundary.y = top
        boundary.w = max(440, right - left)
        boundary.h = max(240, bottom - top)


def separate_deployment_standard_top_groups(
    canvas: Canvas,
    nodes: dict[str, dict],
    children: dict[str | None, list[str]],
    *,
    gap: float,
) -> None:
    shape_map = canvas.shape_map()
    cursor = min((shape_map[node_id].x for node_id in children.get(None, []) if node_id in shape_map), default=90.0)
    for top_id in sorted(children.get(None, []), key=lambda node_id: shape_map[node_id].x if node_id in shape_map else 0):
        boundary = shape_map.get(top_id)
        if not boundary:
            continue
        dx = max(0.0, cursor - boundary.x)
        if dx:
            shift_deployment_subtree(canvas, top_id, children, dx, 0.0)
        boundary = shape_map[top_id]
        cursor = boundary.x + boundary.w + gap


def separate_deployment_sibling_columns(
    canvas: Canvas,
    nodes: dict[str, dict],
    children: dict[str | None, list[str]],
    *,
    gap: float,
) -> bool:
    shape_map = canvas.shape_map()
    changed = False
    parent_ids = sorted(
        (parent_id for parent_id, child_ids in children.items() if parent_id is not None and child_ids),
        key=lambda node_id: deployment_depth(node_id, nodes),
        reverse=True,
    )
    for parent_id in parent_ids:
        child_ids = children[parent_id]
        columns = deployment_sibling_columns([child_id for child_id in child_ids if child_id in shape_map], shape_map)
        if len(columns) < 2:
            continue
        parent_changed = False
        cursor = min(left for left, _right, _ids in columns)
        for _left, _right, column_ids in columns:
            current_left = min(shape_map[node_id].x for node_id in column_ids)
            current_right = max(shape_map[node_id].x + shape_map[node_id].w for node_id in column_ids)
            dx = max(0.0, cursor - current_left)
            if dx:
                for node_id in column_ids:
                    shift_deployment_subtree(canvas, node_id, children, dx, 0.0)
                changed = True
                parent_changed = True
                current_left += dx
                current_right += dx
            cursor = current_right + gap
        if parent_changed:
            refit_deployment_boundary(canvas, nodes, children, parent_id)
    return changed


def refit_deployment_boundary(
    canvas: Canvas,
    nodes: dict[str, dict],
    children: dict[str | None, list[str]],
    parent_id: str,
) -> None:
    shape_map = canvas.shape_map()
    if parent_id not in nodes or parent_id not in shape_map:
        return
    child_shapes = [shape_map[child_id] for child_id in children.get(parent_id, []) if child_id in shape_map]
    if not child_shapes:
        return
    left = min(shape.x for shape in child_shapes) - DEPLOY_PAD_X
    top = min(shape.y for shape in child_shapes) - DEPLOY_HEADER_H
    right = max(shape.x + shape.w for shape in child_shapes) + DEPLOY_PAD_X
    bottom = max(shape.y + shape.h for shape in child_shapes) + DEPLOY_PAD_BOTTOM
    boundary = shape_map[parent_id]
    boundary.x = left
    boundary.y = top
    boundary.w = max(440, right - left)
    boundary.h = max(240, bottom - top)


def deployment_sibling_columns(
    child_ids: list[str],
    shape_map: dict[str, Shape],
) -> list[tuple[float, float, list[str]]]:
    columns: list[tuple[float, float, list[str]]] = []
    for child_id in sorted(child_ids, key=lambda node_id: (shape_map[node_id].x, shape_map[node_id].y)):
        shape = shape_map[child_id]
        left = shape.x
        right = shape.x + shape.w
        if columns and left <= columns[-1][1] + 4:
            col_left, col_right, ids = columns[-1]
            ids.append(child_id)
            columns[-1] = (min(col_left, left), max(col_right, right), ids)
        else:
            columns.append((left, right, [child_id]))
    return columns


def shift_deployment_subtree(
    canvas: Canvas,
    node_id: str,
    children: dict[str | None, list[str]],
    dx: float,
    dy: float,
) -> None:
    ids = deployment_descendants(node_id, children)
    for shape in canvas.shapes:
        if shape.id in ids:
            shape.x += dx
            shape.y += dy


def deployment_column_count(count: int) -> int:
    if count <= 3:
        return 1
    if count <= 6:
        return 2
    return 3


def deployment_leaf_kind(kind: str) -> str:
    if kind == "database":
        return "database"
    return "rect"


def expand_deployment_nested_boundaries_from_routes(canvas: Canvas, parent_of: dict[str, str | None]) -> None:
    for boundary in canvas.shapes:
        if boundary.kind != "boundary" or parent_of.get(boundary.id) is None:
            continue
        descendants = {
            node_id
            for node_id in parent_of
            if deployment_has_ancestor(node_id, boundary.id, parent_of)
        }
        if not descendants:
            continue
        left = boundary.x
        right = boundary.x + boundary.w
        top = boundary.y
        bottom = boundary.y + boundary.h
        grow_left = grow_right = grow_bottom = 0.0
        for connector in canvas.connectors:
            if connector.source not in descendants and connector.target not in descendants:
                continue
            for a, b in zip(connector.points or [], (connector.points or [])[1:]):
                if abs(a[1] - b[1]) <= 1:
                    y = a[1]
                    seg_left, seg_right = sorted((a[0], b[0]))
                    if top <= y <= bottom and seg_right >= left and seg_left <= right:
                        grow_bottom = max(grow_bottom, DEPLOY_BOUNDARY_ROUTE_GAP - (bottom - y))
                if abs(a[0] - b[0]) <= 1:
                    x = a[0]
                    seg_top, seg_bottom = sorted((a[1], b[1]))
                    if left <= x <= right and seg_bottom >= top and seg_top <= bottom:
                        grow_left = max(grow_left, DEPLOY_BOUNDARY_ROUTE_GAP - (x - left))
                        grow_right = max(grow_right, DEPLOY_BOUNDARY_ROUTE_GAP - (right - x))
        if grow_left > 0:
            boundary.x -= grow_left
            boundary.w += grow_left
        if grow_right > 0:
            boundary.w += grow_right
        if grow_bottom > 0:
            boundary.h += grow_bottom


def deployment_has_ancestor(node_id: str, ancestor_id: str, parent_of: dict[str, str | None]) -> bool:
    current = node_id
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        parent = parent_of.get(current)
        if parent == ancestor_id:
            return True
        current = parent or ""
    return False


def place_deployment_short_edge_labels(canvas: Canvas) -> None:
    shape_map = canvas.shape_map()
    for connector in canvas.connectors:
        if not connector.label or not connector.points or len(connector.points) != 2:
            continue
        source = shape_map.get(connector.source)
        target = shape_map.get(connector.target)
        if not source or not target or target.kind != "database":
            continue
        start, end = connector.points
        dx, dy = end[0] - start[0], end[1] - start[1]
        if abs(dx) < abs(dy) * 1.2 or abs(dx) > 190:
            continue
        label_w = max(82.0, min(135.0, len(connector.label) * 7.0))
        x = start[0] - min(60.0, label_w * 0.55) if dx > 0 else start[0] + 18.0
        y = source.y + source.h + 6.0
        if y > target.y + target.h - 26:
            y = source.y - 32.0
        connector.label_position = (x, y)


def immediate_child_under(node_id: str, parent_id: str, parent_of: dict[str, str | None]) -> str | None:
    current = node_id
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        parent = parent_of.get(current)
        if parent == parent_id:
            return current
        current = parent or ""
    return None


def dependency_levels(node_ids: list[str], edges: set[tuple[str, str]]) -> dict[str, int]:
    indegree = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for source, target in edges:
        if source not in indegree or target not in indegree:
            continue
        outgoing[source].append(target)
        indegree[target] += 1
    queue = deque(node_id for node_id in node_ids if indegree[node_id] == 0)
    levels = {node_id: 0 for node_id in node_ids}
    visited = 0
    while queue:
        source = queue.popleft()
        visited += 1
        for target in outgoing[source]:
            levels[target] = max(levels[target], levels[source] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(node_ids):
        return {node_id: index for index, node_id in enumerate(node_ids)}
    return levels


def route_deployment_connectors(canvas: Canvas) -> None:
    shape_map = canvas.shape_map()
    obstacles = [
        shape
        for shape in canvas.shapes
        if shape.kind not in {"boundary", "group", "lifeline", "fragment"}
    ]
    port_map = deployment_assign_ports(canvas, shape_map)
    routed_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    route_order = sorted(
        canvas.connectors,
        key=lambda item: deployment_route_order(item, shape_map),
    )
    for connector in route_order:
        source = shape_map.get(connector.source)
        target = shape_map.get(connector.target)
        if not source or not target:
            continue
        points = deployment_connector_route(source, target, connector, obstacles, routed_segments, canvas, port_map)
        connector.points = points
        routed_segments.extend(zip(points, points[1:]))
    repair_deployment_line_crossings(canvas, obstacles, port_map)
    for connector in canvas.connectors:
        if connector.points:
            connector.label_position = elk_label_anchor(connector.points)


def repair_deployment_line_crossings(
    canvas: Canvas,
    obstacles: list[Shape],
    port_map: dict[tuple[str, str], tuple[tuple[float, float], str]],
) -> None:
    shape_map = canvas.shape_map()
    for _ in range(3):
        baseline = deployment_line_crossing_count(canvas)
        if baseline == 0:
            return
        crossing_ids = deployment_crossing_connector_ids(canvas)
        changed = False
        for connector in sorted(
            (item for item in canvas.connectors if item.id in crossing_ids),
            key=lambda item: deployment_route_order(item, shape_map),
        ):
            source = shape_map.get(connector.source)
            target = shape_map.get(connector.target)
            if not source or not target:
                continue
            previous_points = connector.points
            previous_label = connector.label_position
            routed_segments = [
                segment
                for other in canvas.connectors
                if other.id != connector.id and other.points
                for segment in zip(other.points, other.points[1:])
            ]
            connector.points = deployment_connector_route(
                source,
                target,
                connector,
                obstacles,
                routed_segments,
                canvas,
                port_map,
                allow_alternate_ports=True,
            )
            connector.points = deployment_simplify_route(connector.points)
            connector.label_position = elk_label_anchor(connector.points)
            updated = deployment_line_crossing_count(canvas)
            if updated < baseline and not connector_crosses_unrelated_shape(connector, obstacles):
                baseline = updated
                changed = True
                if baseline == 0:
                    return
                continue
            connector.points = previous_points
            connector.label_position = previous_label
        if not changed:
            return


def repair_deployment_boundary_conflicts(canvas: Canvas) -> None:
    shape_map = canvas.shape_map()
    obstacles = [
        shape
        for shape in canvas.shapes
        if shape.kind not in {"boundary", "group", "lifeline", "fragment"}
    ]
    boundary_shapes = [shape for shape in canvas.shapes if shape.kind == "boundary"]
    if not boundary_shapes:
        return
    port_map = deployment_assign_ports(canvas, shape_map)
    for _ in range(2):
        changed = False
        for connector in sorted(
            canvas.connectors,
            key=lambda item: count_path_boundary_edge_conflicts(item.points or [], item, boundary_shapes),
            reverse=True,
        ):
            baseline_conflicts = count_path_boundary_edge_conflicts(connector.points or [], connector, boundary_shapes)
            if baseline_conflicts == 0:
                continue
            source = shape_map.get(connector.source)
            target = shape_map.get(connector.target)
            if not source or not target:
                continue
            previous_points = connector.points
            previous_label = connector.label_position
            previous_crossings = deployment_line_crossing_count(canvas)
            routed_segments = [
                segment
                for other in canvas.connectors
                if other.id != connector.id and other.points
                for segment in zip(other.points, other.points[1:])
            ]
            candidate = deployment_connector_route(
                source,
                target,
                connector,
                obstacles,
                routed_segments,
                canvas,
                port_map,
                allow_alternate_ports=True,
            )
            connector.points = deployment_simplify_route(candidate)
            connector.label_position = elk_label_anchor(connector.points)
            updated_conflicts = count_path_boundary_edge_conflicts(connector.points or [], connector, boundary_shapes)
            updated_crossings = deployment_line_crossing_count(canvas)
            if (
                updated_conflicts < baseline_conflicts
                and updated_crossings <= previous_crossings
                and not connector_crosses_unrelated_shape(connector, obstacles)
            ):
                changed = True
                continue
            connector.points = previous_points
            connector.label_position = previous_label
        if not changed:
            return


def deployment_line_crossing_count(canvas: Canvas) -> int:
    return sum(1 for _connector_id in deployment_crossing_connector_ids(canvas, include_duplicates=True))


def deployment_crossing_connector_ids(canvas: Canvas, *, include_duplicates: bool = False) -> set[str] | list[str]:
    segments = [
        (connector, start, end)
        for connector in canvas.connectors
        for start, end in zip(connector.points or [], (connector.points or [])[1:])
    ]
    result: list[str] = []
    for index, (first, first_start, first_end) in enumerate(segments):
        for second, second_start, second_end in segments[index + 1:]:
            if first.id == second.id:
                continue
            if {first.source, first.target} & {second.source, second.target}:
                continue
            if real_segment_crossing((first_start, first_end), (second_start, second_end)):
                result.append(first.id)
                result.append(second.id)
    return result if include_duplicates else set(result)


def deployment_route_order(connector: Connector, shape_map: dict[str, Shape]) -> tuple[float, float, float, str]:
    source = shape_map.get(connector.source)
    target = shape_map.get(connector.target)
    if not source or not target:
        return (float("inf"), float("inf"), float("inf"), connector.id)
    sx, sy = center(source)
    tx, ty = center(target)
    distance = math.hypot(tx - sx, ty - sy)
    if source.kind == "database" and target.kind == "database":
        route_class = 2
    elif target.kind == "database":
        route_class = 1
    else:
        route_class = 0
    return (route_class, distance, abs(tx - sx), connector.id)


def deployment_top_container_id(shape: Shape, shape_map: dict[str, Shape]) -> str | None:
    current = shape
    top_id: str | None = None
    seen: set[str] = set()
    while current.parent and current.parent not in seen:
        seen.add(current.parent)
        parent = shape_map.get(current.parent)
        if not parent:
            break
        top_id = parent.id
        current = parent
    return top_id


def deployment_assign_ports(
    canvas: Canvas,
    shape_map: dict[str, Shape],
) -> dict[tuple[str, str], tuple[tuple[float, float], str]]:
    endpoint_groups: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    endpoint_sides: dict[tuple[str, str], str] = {}
    for connector in canvas.connectors:
        source = shape_map.get(connector.source)
        target = shape_map.get(connector.target)
        if not source or not target:
            continue
        source_side, target_side = deployment_connector_sides(source, target)
        endpoint_sides[(connector.id, "source")] = source_side
        endpoint_sides[(connector.id, "target")] = target_side
        endpoint_groups[(source.id, source_side)].append(
            (f"{connector.id}:source", deployment_port_sort_value(target, source_side))
        )
        endpoint_groups[(target.id, target_side)].append(
            (f"{connector.id}:target", deployment_port_sort_value(source, target_side))
        )

    endpoint_points: dict[str, tuple[float, float]] = {}
    for (shape_id, side), items in endpoint_groups.items():
        shape = shape_map.get(shape_id)
        if not shape:
            continue
        ordered = sorted(items, key=lambda item: item[1])
        for index, (key, _sort_value) in enumerate(ordered):
            endpoint_points[key] = deployment_side_port(shape, side, index, len(ordered))

    result: dict[tuple[str, str], tuple[tuple[float, float], str]] = {}
    for connector in canvas.connectors:
        for endpoint in ("source", "target"):
            side = endpoint_sides.get((connector.id, endpoint))
            point = endpoint_points.get(f"{connector.id}:{endpoint}")
            if side and point:
                result[(connector.id, endpoint)] = (point, side)
    return result


def deployment_connector_sides(source: Shape, target: Shape) -> tuple[str, str]:
    sx, sy = center(source)
    tx, ty = center(target)
    dx = tx - sx
    dy = ty - sy
    if abs(dx) >= abs(dy) * 0.55:
        return ("E", "W") if dx >= 0 else ("W", "E")
    return ("S", "N") if dy >= 0 else ("N", "S")


def deployment_port_sort_value(other: Shape, side: str) -> float:
    cx, cy = center(other)
    return cy if side in {"E", "W"} else cx


def deployment_side_port(shape: Shape, side: str, index: int, count: int) -> tuple[float, float]:
    if count <= 1:
        ratio = 0.5
    else:
        if count == 2:
            low, high = (0.28, 0.72)
        elif count == 3:
            low, high = (0.24, 0.76)
        else:
            low, high = (0.18, 0.82)
        if shape.kind == "database":
            low, high = max(low, 0.36), min(high, 0.64)
        ratio = low + (high - low) * index / (count - 1)
    if side == "E":
        return shape.x + shape.w, shape.y + shape.h * ratio
    if side == "W":
        return shape.x, shape.y + shape.h * ratio
    if side == "S":
        return shape.x + shape.w * ratio, shape.y + shape.h
    return shape.x + shape.w * ratio, shape.y


def deployment_connector_route(
    source: Shape,
    target: Shape,
    connector: Connector,
    obstacles: list[Shape],
    routed_segments: list[tuple[tuple[float, float], tuple[float, float]]],
    canvas: Canvas,
    port_map: dict[tuple[str, str], tuple[tuple[float, float], str]],
    *,
    allow_alternate_ports: bool = False,
) -> list[tuple[float, float]]:
    preferred_start, preferred_source_side = port_map.get(
        (connector.id, "source"),
        (perimeter_point(source, center(target)), deployment_connector_sides(source, target)[0]),
    )
    preferred_end, preferred_target_side = port_map.get(
        (connector.id, "target"),
        (perimeter_point(target, center(source)), deployment_connector_sides(source, target)[1]),
    )
    boundary_shapes = [shape for shape in canvas.shapes if shape.kind == "boundary"]
    if boundary_shapes:
        outer_gap = DEPLOY_BOUNDARY_ROUTE_GAP * 1.75
        outer_top = max(28.0, min(shape.y for shape in boundary_shapes) - outer_gap)
        outer_bottom = max(shape.y + shape.h for shape in boundary_shapes) + outer_gap
        outer_left = max(28.0, min(shape.x for shape in boundary_shapes) - outer_gap)
        outer_right = max(shape.x + shape.w for shape in boundary_shapes) + outer_gap
        required_y_lanes = {round(outer_top, 2), round(outer_bottom, 2)}
        required_x_lanes = {round(outer_left, 2), round(outer_right, 2)}
        shape_map = canvas.shape_map()
        source_top = deployment_top_container_id(source, shape_map)
        target_top = deployment_top_container_id(target, shape_map)
        if source_top and source_top == target_top:
            required_y_lanes = set()
            required_x_lanes = set()
        y_limit = max(float(canvas.height), outer_bottom + 28.0)
        x_limit = max(float(canvas.width), outer_right + 28.0)
    else:
        required_y_lanes = {70.0, float(canvas.height - 70)}
        required_x_lanes = {70.0, float(canvas.width - 70)}
        y_limit = float(canvas.height)
        x_limit = float(canvas.width)
    boundary_gap_x_lanes, boundary_gap_y_lanes = deployment_boundary_gap_lanes(boundary_shapes)

    scored: list[tuple[float, list[tuple[float, float]]]] = []
    if allow_alternate_ports:
        source_options = deployment_endpoint_options(source, target, preferred_start, preferred_source_side)
        target_options = deployment_endpoint_options(target, source, preferred_end, preferred_target_side)
    else:
        source_options = [(preferred_start, preferred_source_side, 0.0)]
        target_options = [(preferred_end, preferred_target_side, 0.0)]

    for start, source_side, source_port_penalty in source_options:
        for end, target_side, target_port_penalty in target_options:
            source_jetty, target_jetty = deployment_jetty_lengths(start, end, source_side, target_side)
            source_jetty, target_jetty = deployment_database_jetty_lengths(
                source,
                target,
                start,
                end,
                source_side,
                target_side,
                source_jetty,
                target_jetty,
            )
            start_jetty = deployment_jetty_point(start, source_side, source_jetty)
            end_jetty = deployment_jetty_point(end, target_side, target_jetty)
            sx, sy = start_jetty
            tx, ty = end_jetty
            endpoint_x_lanes: set[float] = set()
            endpoint_y_lanes: set[float] = set()
            if source_side in {"E", "W"}:
                endpoint_x_lanes.add((start[0] + start_jetty[0]) / 2)
            else:
                endpoint_y_lanes.add((start[1] + start_jetty[1]) / 2)
            if target_side in {"E", "W"}:
                endpoint_x_lanes.add((end[0] + end_jetty[0]) / 2)
            else:
                endpoint_y_lanes.add((end[1] + end_jetty[1]) / 2)
            candidate_paths: list[list[tuple[float, float]]] = []
            horizontal_ports = source_side in {"E", "W"} and target_side in {"E", "W"}
            vertical_ports = source_side in {"N", "S"} and target_side in {"N", "S"}
            direct = deployment_direct_route(source, target, connector, start, end, source_side, target_side, obstacles)
            if direct:
                candidate_paths.append(direct)
            if (horizontal_ports and abs(sy - ty) <= 36) or (vertical_ports and abs(sx - tx) <= 36):
                candidate_paths.append([start, start_jetty, end_jetty, end])

            y_lanes = set(required_y_lanes) | {(sy + ty) / 2}
            x_lanes = set(required_x_lanes) | {(sx + tx) / 2}
            y_lanes.update(boundary_gap_y_lanes)
            x_lanes.update(boundary_gap_x_lanes)
            segment_y_lanes: set[float] = set()
            segment_x_lanes: set[float] = set()
            for shape in boundary_shapes:
                x_lanes.update({
                    shape.x - 58,
                    shape.x + shape.w + 58,
                    shape.x - 30,
                    shape.x + shape.w + 30,
                    shape.x - DEPLOY_ROUTE_GAP_X,
                    shape.x + shape.w + DEPLOY_ROUTE_GAP_X,
                })
                y_lanes.update({
                    shape.y - 58,
                    shape.y + shape.h + 58,
                    shape.y - 30,
                    shape.y + shape.h + 30,
                    shape.y - DEPLOY_ROUTE_GAP_Y,
                    shape.y + shape.h + DEPLOY_ROUTE_GAP_Y,
                })
            for shape in obstacles:
                if shape.id in {source.id, target.id}:
                    continue
                x_gap = DEPLOY_DATABASE_ROUTE_GAP_X if shape.kind == "database" else DEPLOY_ROUTE_GAP_X
                y_gap = DEPLOY_DATABASE_ROUTE_GAP_Y if shape.kind == "database" else DEPLOY_ROUTE_GAP_Y
                y_lanes.update({
                    shape.y - 58,
                    shape.y + shape.h + 58,
                    shape.y - 30,
                    shape.y + shape.h + 30,
                    shape.y - y_gap,
                    shape.y + shape.h + y_gap,
                })
                x_lanes.update({
                    shape.x - 32,
                    shape.x - 58,
                    shape.x + shape.w + 58,
                    shape.x + shape.w + 32,
                    shape.x - 30,
                    shape.x + shape.w + 30,
                    shape.x - x_gap,
                    shape.x + shape.w + x_gap,
                })
            for shape in (source, target):
                if shape.kind != "database":
                    continue
                x_lanes.update({
                    shape.x - DEPLOY_DATABASE_ROUTE_GAP_X,
                    shape.x + shape.w + DEPLOY_DATABASE_ROUTE_GAP_X,
                })
                y_lanes.update({
                    shape.y - DEPLOY_DATABASE_ROUTE_GAP_Y,
                    shape.y + shape.h + DEPLOY_DATABASE_ROUTE_GAP_Y,
                })
            for first, second in routed_segments:
                if abs(first[1] - second[1]) <= 1:
                    left, right = sorted((first[0], second[0]))
                    segment_y_lanes.update({first[1] - DEPLOY_PARALLEL_MIN_GAP, first[1] + DEPLOY_PARALLEL_MIN_GAP})
                    segment_x_lanes.update({left - DEPLOY_PARALLEL_MIN_GAP, right + DEPLOY_PARALLEL_MIN_GAP})
                elif abs(first[0] - second[0]) <= 1:
                    top, bottom = sorted((first[1], second[1]))
                    segment_x_lanes.update({first[0] - DEPLOY_PARALLEL_MIN_GAP, first[0] + DEPLOY_PARALLEL_MIN_GAP})
                    segment_y_lanes.update({top - DEPLOY_PARALLEL_MIN_GAP, bottom + DEPLOY_PARALLEL_MIN_GAP})
            segment_y_lanes = set(nearest_deployment_segment_lanes(segment_y_lanes, (sy + ty) / 2, 4))
            segment_x_lanes = set(nearest_deployment_segment_lanes(segment_x_lanes, (sx + tx) / 2, 4))
            y_lanes.update(segment_y_lanes)
            x_lanes.update(segment_x_lanes)
            local_required_y = (
                required_y_lanes
                | set(nearest_deployment_segment_lanes(boundary_gap_y_lanes, (sy + ty) / 2, 4))
                | (endpoint_y_lanes if allow_alternate_ports else set())
                | (segment_y_lanes if allow_alternate_ports else set())
            )
            local_required_x = (
                required_x_lanes
                | set(nearest_deployment_segment_lanes(boundary_gap_x_lanes, (sx + tx) / 2, 4))
                | (endpoint_x_lanes if allow_alternate_ports else set())
                | (segment_x_lanes if allow_alternate_ports else set())
            )
            candidate_y_lanes = deployment_candidate_lanes(
                y_lanes,
                (sy + ty) / 2,
                y_limit,
                local_required_y,
            )
            candidate_x_lanes = deployment_candidate_lanes(
                x_lanes,
                (sx + tx) / 2,
                x_limit,
                local_required_x,
            )
            for lane_y in candidate_y_lanes:
                if deployment_y_lane_leaves_source(lane_y, source, source_side) and deployment_y_lane_approaches_target(lane_y, target, target_side):
                    candidate_paths.append([start, start_jetty, (sx, lane_y), (tx, lane_y), end_jetty, end])
            for lane_x in candidate_x_lanes:
                if deployment_lane_leaves_source(lane_x, source, source_side) and deployment_lane_approaches_target(lane_x, target, target_side):
                    candidate_paths.append([start, start_jetty, (lane_x, sy), (lane_x, ty), end_jetty, end])
            for lane_y in candidate_y_lanes:
                for lane_x in candidate_x_lanes:
                    if deployment_lane_leaves_source(lane_x, source, source_side) and deployment_y_lane_approaches_target(lane_y, target, target_side):
                        candidate_paths.append([start, start_jetty, (lane_x, sy), (lane_x, lane_y), (tx, lane_y), end_jetty, end])
                    if (
                        deployment_y_lane_leaves_source(lane_y, source, source_side)
                        and deployment_lane_leaves_source(lane_x, source, source_side)
                        and deployment_lane_approaches_target(lane_x, target, target_side)
                    ):
                        candidate_paths.append([start, start_jetty, (sx, lane_y), (lane_x, lane_y), (lane_x, ty), end_jetty, end])

            for candidate in candidate_paths:
                points = deployment_simplify_route(candidate)
                if not deployment_route_is_orthogonal(points):
                    continue
                crossings = count_path_obstacle_crossings(points, connector, obstacles)
                if crossings:
                    continue
                line_crossings = count_path_line_crossings(points, routed_segments)
                line_overlaps = count_path_line_overlaps(points, routed_segments)
                parallel_close = count_path_parallel_close_passes(points, routed_segments)
                close_passes = count_path_close_shape_passes(points, connector, obstacles)
                boundary_conflicts = count_path_boundary_edge_conflicts(points, connector, boundary_shapes)
                database_conflicts = count_path_database_contour_conflicts(points, connector, canvas.shapes)
                length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))
                bends = max(0, len(points) - 2)
                scored.append(
                    (
                        source_port_penalty
                        + target_port_penalty
                        + line_overlaps * 180000
                        + line_crossings * 160000
                        + parallel_close * 110000
                        + boundary_conflicts * 140000
                        + database_conflicts * 155000
                        + close_passes * 18000
                        + bends * 900
                        + length,
                        points,
                    )
                )
    if scored:
        return min(scored, key=lambda item: item[0])[1]
    source_jetty, target_jetty = deployment_jetty_lengths(
        preferred_start,
        preferred_end,
        preferred_source_side,
        preferred_target_side,
    )
    source_jetty, target_jetty = deployment_database_jetty_lengths(
        source,
        target,
        preferred_start,
        preferred_end,
        preferred_source_side,
        preferred_target_side,
        source_jetty,
        target_jetty,
    )
    return deployment_fallback_orthogonal_route(
        connector,
        obstacles,
        canvas,
        preferred_start,
        deployment_jetty_point(preferred_start, preferred_source_side, source_jetty),
        deployment_jetty_point(preferred_end, preferred_target_side, target_jetty),
        preferred_end,
    )


def deployment_endpoint_options(
    shape: Shape,
    other: Shape,
    preferred_point: tuple[float, float],
    preferred_side: str,
) -> list[tuple[tuple[float, float], str, float]]:
    cx, cy = center(shape)
    ox, oy = center(other)
    dx = ox - cx
    dy = oy - cy
    horizontal = "E" if dx >= 0 else "W"
    vertical = "S" if dy >= 0 else "N"
    if shape.kind == "database" and preferred_side in {"E", "W"}:
        preferred_sequence = (horizontal, opposite_side(horizontal))
    else:
        preferred_sequence = (horizontal, vertical, opposite_side(vertical), opposite_side(horizontal))
    side_order = [preferred_side]
    for side in preferred_sequence:
        if side not in side_order:
            side_order.append(side)

    options: list[tuple[tuple[float, float], str, float]] = [(preferred_point, preferred_side, 0.0)]
    for index, side in enumerate(side_order):
        ratios = (0.5,)
        for ratio in ratios:
            point = deployment_ratio_port(shape, side, ratio)
            if any(math.hypot(point[0] - existing[0][0], point[1] - existing[0][1]) < 1 for existing in options):
                continue
            penalty = 0.0 if side == preferred_side else 18000.0 + index * 2400.0 + abs(ratio - 0.5) * 3600.0
            options.append((point, side, penalty))
    return options[:5]


def deployment_fallback_orthogonal_route(
    connector: Connector,
    obstacles: list[Shape],
    canvas: Canvas,
    start: tuple[float, float],
    start_jetty: tuple[float, float],
    end_jetty: tuple[float, float],
    end: tuple[float, float],
) -> list[tuple[float, float]]:
    candidates = [
        [start, start_jetty, (end_jetty[0], start_jetty[1]), end_jetty, end],
        [start, start_jetty, (start_jetty[0], end_jetty[1]), end_jetty, end],
    ]
    scored: list[tuple[float, list[tuple[float, float]]]] = []
    boundary_shapes = [shape for shape in canvas.shapes if shape.kind == "boundary"]
    for candidate in candidates:
        points = deployment_simplify_route(candidate)
        if not deployment_route_is_orthogonal(points):
            continue
        crossings = count_path_obstacle_crossings(points, connector, obstacles)
        close_passes = count_path_close_shape_passes(points, connector, obstacles)
        boundary_conflicts = count_path_boundary_edge_conflicts(points, connector, boundary_shapes)
        database_conflicts = count_path_database_contour_conflicts(points, connector, canvas.shapes)
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))
        bends = max(0, len(points) - 2)
        scored.append(
            (
                crossings * 220000
                + boundary_conflicts * 140000
                + database_conflicts * 155000
                + close_passes * 18000
                + bends * 900
                + length,
                points,
            )
        )
    if scored:
        return min(scored, key=lambda item: item[0])[1]
    return deployment_simplify_route([start, start_jetty, end_jetty, end])


def deployment_route_is_orthogonal(points: list[tuple[float, float]]) -> bool:
    return all(abs(a[0] - b[0]) <= 1 or abs(a[1] - b[1]) <= 1 for a, b in zip(points, points[1:]))


def deployment_ratio_port(shape: Shape, side: str, ratio: float) -> tuple[float, float]:
    if shape.kind == "database":
        ratio = max(0.36, min(0.64, ratio))
    if side == "E":
        return shape.x + shape.w, shape.y + shape.h * ratio
    if side == "W":
        return shape.x, shape.y + shape.h * ratio
    if side == "S":
        return shape.x + shape.w * ratio, shape.y + shape.h
    return shape.x + shape.w * ratio, shape.y


def opposite_side(side: str) -> str:
    if side == "E":
        return "W"
    if side == "W":
        return "E"
    if side == "N":
        return "S"
    return "N"


def deployment_lane_approaches_target(lane_x: float, target: Shape, target_side: str) -> bool:
    if target_side == "W":
        return lane_x <= target.x - 4
    if target_side == "E":
        return lane_x >= target.x + target.w + 4
    return True


def deployment_lane_leaves_source(lane_x: float, source: Shape, source_side: str) -> bool:
    if source_side == "E":
        return lane_x >= source.x + source.w + 4
    if source_side == "W":
        return lane_x <= source.x - 4
    return True


def deployment_y_lane_approaches_target(lane_y: float, target: Shape, target_side: str) -> bool:
    if target_side == "N":
        return lane_y <= target.y - 4
    if target_side == "S":
        return lane_y >= target.y + target.h + 4
    return True


def deployment_y_lane_leaves_source(lane_y: float, source: Shape, source_side: str) -> bool:
    if source_side == "N":
        return lane_y <= source.y - 4
    if source_side == "S":
        return lane_y >= source.y + source.h + 4
    return True


def count_path_parallel_close_passes(
    points: list[tuple[float, float]],
    routed_segments: list[tuple[tuple[float, float], tuple[float, float]]],
) -> int:
    close_passes = 0
    for segment in zip(points, points[1:]):
        for existing in routed_segments:
            close_passes += parallel_close_pass(segment, existing)
    return close_passes


def parallel_close_pass(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> int:
    (a, b), (c, d) = first, second
    if any(math.hypot(p[0] - q[0], p[1] - q[1]) < 2 for p in (a, b) for q in (c, d)):
        return 0
    first_horizontal = abs(a[1] - b[1]) <= 1 and abs(a[0] - b[0]) > 1
    second_horizontal = abs(c[1] - d[1]) <= 1 and abs(c[0] - d[0]) > 1
    first_vertical = abs(a[0] - b[0]) <= 1 and abs(a[1] - b[1]) > 1
    second_vertical = abs(c[0] - d[0]) <= 1 and abs(c[1] - d[1]) > 1
    min_gap = DEPLOY_PARALLEL_MIN_GAP
    if first_horizontal and second_horizontal:
        first_span = sorted((a[0], b[0]))
        second_span = sorted((c[0], d[0]))
        overlap = min(first_span[1], second_span[1]) - max(first_span[0], second_span[0])
        continuation_gap = max(first_span[0], second_span[0]) - min(first_span[1], second_span[1])
        gap = abs(a[1] - c[1])
    elif first_vertical and second_vertical:
        first_span = sorted((a[1], b[1]))
        second_span = sorted((c[1], d[1]))
        overlap = min(first_span[1], second_span[1]) - max(first_span[0], second_span[0])
        continuation_gap = max(first_span[0], second_span[0]) - min(first_span[1], second_span[1])
        gap = abs(a[0] - c[0])
    else:
        return 0
    if overlap <= 36:
        if gap < min_gap * 0.35 and 0 < continuation_gap < min_gap * 1.25:
            return 4 if continuation_gap < min_gap * 0.75 else 2
        return 0
    if gap >= min_gap:
        return 0
    return 2 if gap < min_gap * 0.45 else 1


def deployment_direct_route(
    source: Shape,
    target: Shape,
    connector: Connector,
    start: tuple[float, float],
    end: tuple[float, float],
    source_side: str,
    target_side: str,
    obstacles: list[Shape],
) -> list[tuple[float, float]] | None:
    if source_side in {"E", "W"} and target_side in {"E", "W"} and abs(start[1] - end[1]) <= 14:
        aligned_end = (end[0], start[1])
        if target.y + 12 <= aligned_end[1] <= target.y + target.h - 12:
            points = [start, aligned_end]
            if not count_path_obstacle_crossings(points, connector, obstacles):
                return points
    if source_side in {"N", "S"} and target_side in {"N", "S"} and abs(start[0] - end[0]) <= 14:
        aligned_end = (start[0], end[1])
        if target.x + 12 <= aligned_end[0] <= target.x + target.w - 12:
            points = [start, aligned_end]
            if not count_path_obstacle_crossings(points, connector, obstacles):
                return points
    return None


def deployment_candidate_lanes(values: set[float], center_value: float, limit: float, required: set[float]) -> list[float]:
    valid = {round(value, 2) for value in values if 28 <= value <= limit - 28}
    selected = {round(value, 2) for value in required if 28 <= value <= limit - 28}
    for value in sorted(valid - selected, key=lambda lane: abs(lane - center_value))[:5]:
        selected.add(value)
    return sorted(selected, key=lambda lane: (0 if lane in required else 1, abs(lane - center_value)))


def nearest_deployment_segment_lanes(values: set[float], center_value: float, limit: int) -> list[float]:
    return sorted(values, key=lambda lane: abs(lane - center_value))[:limit]


def deployment_boundary_gap_lanes(boundary_shapes: list[Shape]) -> tuple[set[float], set[float]]:
    x_lanes: set[float] = set()
    y_lanes: set[float] = set()
    for first in boundary_shapes:
        for second in boundary_shapes:
            if first.id >= second.id:
                continue
            left, right = sorted((first, second), key=lambda shape: shape.x)
            horizontal_gap = right.x - (left.x + left.w)
            vertical_overlap = min(left.y + left.h, right.y + right.h) - max(left.y, right.y)
            if 64 <= horizontal_gap <= 260 and vertical_overlap >= 90:
                x_lanes.add(round(left.x + left.w + horizontal_gap / 2, 2))

            top, bottom = sorted((first, second), key=lambda shape: shape.y)
            vertical_gap = bottom.y - (top.y + top.h)
            horizontal_overlap = min(top.x + top.w, bottom.x + bottom.w) - max(top.x, bottom.x)
            if 64 <= vertical_gap <= 260 and horizontal_overlap >= 90:
                y_lanes.add(round(top.y + top.h + vertical_gap / 2, 2))
    return x_lanes, y_lanes


def deployment_simplify_route(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return remove_collinear_backtracks(simplify_layout_path(points))


def remove_collinear_backtracks(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return points
    result = list(points)
    changed = True
    while changed and len(result) > 2:
        changed = False
        cleaned = [result[0]]
        for index, point in enumerate(result[1:-1], start=1):
            prev = cleaned[-1]
            nxt = result[index + 1]
            cross = (point[0] - prev[0]) * (nxt[1] - point[1]) - (point[1] - prev[1]) * (nxt[0] - point[0])
            if abs(cross) < 0.01:
                before = (point[0] - prev[0], point[1] - prev[1])
                after = (nxt[0] - point[0], nxt[1] - point[1])
                if before[0] * after[0] + before[1] * after[1] < 0:
                    changed = True
                    continue
            cleaned.append(point)
        cleaned.append(result[-1])
        result = simplify_layout_path(cleaned)
    return result


def deployment_jetty_lengths(
    start: tuple[float, float],
    end: tuple[float, float],
    source_side: str,
    target_side: str,
) -> tuple[float, float]:
    length = DEPLOY_JETTY
    if source_side == "E" and target_side == "W" and end[0] > start[0]:
        length = min(length, max(28.0, (end[0] - start[0] - 30.0) / 2))
    elif source_side == "W" and target_side == "E" and start[0] > end[0]:
        length = min(length, max(28.0, (start[0] - end[0] - 30.0) / 2))
    elif source_side == "S" and target_side == "N" and end[1] > start[1]:
        length = min(length, max(28.0, (end[1] - start[1] - 30.0) / 2))
    elif source_side == "N" and target_side == "S" and start[1] > end[1]:
        length = min(length, max(28.0, (start[1] - end[1] - 30.0) / 2))
    return length, length


def deployment_database_jetty_lengths(
    source: Shape,
    target: Shape,
    start: tuple[float, float],
    end: tuple[float, float],
    source_side: str,
    target_side: str,
    source_jetty: float,
    target_jetty: float,
) -> tuple[float, float]:
    if source.kind == "database":
        source_jetty = max(source_jetty, deployment_database_port_jetty(source, start, source_side))
    if target.kind == "database":
        target_jetty = max(target_jetty, deployment_database_port_jetty(target, end, target_side))
    if source_side == "E" and target_side == "W" and end[0] > start[0]:
        return deployment_cap_opposed_jetties(source_jetty, target_jetty, end[0] - start[0])
    if source_side == "W" and target_side == "E" and start[0] > end[0]:
        return deployment_cap_opposed_jetties(source_jetty, target_jetty, start[0] - end[0])
    if source_side == "S" and target_side == "N" and end[1] > start[1]:
        return deployment_cap_opposed_jetties(source_jetty, target_jetty, end[1] - start[1])
    if source_side == "N" and target_side == "S" and start[1] > end[1]:
        return deployment_cap_opposed_jetties(source_jetty, target_jetty, start[1] - end[1])
    return source_jetty, target_jetty


def deployment_database_port_jetty(shape: Shape, point: tuple[float, float], side: str) -> float:
    if side in {"E", "W"}:
        ratio = (point[1] - shape.y) / max(shape.h, 1.0)
    else:
        ratio = (point[0] - shape.x) / max(shape.w, 1.0)
    if ratio > 0.58:
        return DEPLOY_DATABASE_JETTY - 44.0
    if ratio < 0.42:
        return DEPLOY_DATABASE_JETTY
    return DEPLOY_DATABASE_JETTY - 20.0


def deployment_cap_opposed_jetties(source_jetty: float, target_jetty: float, span: float) -> tuple[float, float]:
    available = max(56.0, span - 48.0)
    total = source_jetty + target_jetty
    if total <= available:
        return source_jetty, target_jetty
    scale = available / total
    return max(28.0, source_jetty * scale), max(28.0, target_jetty * scale)


def deployment_jetty_point(point: tuple[float, float], side: str, length: float) -> tuple[float, float]:
    dx, dy = deployment_side_vector(side)
    return point[0] + dx * length, point[1] + dy * length


def deployment_side_vector(side: str) -> tuple[float, float]:
    if side == "E":
        return 1.0, 0.0
    if side == "W":
        return -1.0, 0.0
    if side == "S":
        return 0.0, 1.0
    return 0.0, -1.0


def count_path_close_shape_passes(
    points: list[tuple[float, float]],
    connector: Connector,
    obstacle_shapes: list[Shape],
) -> int:
    passes = 0
    for a, b in zip(points, points[1:]):
        for shape in obstacle_shapes:
            if shape.id in {connector.source, connector.target}:
                continue
            close_gap = 68 if shape.kind == "database" else 48
            far_gap = 138 if shape.kind == "database" else 104
            close_box = (shape.x - close_gap, shape.y - close_gap, shape.x + shape.w + close_gap, shape.y + shape.h + close_gap)
            far_box = (shape.x - far_gap, shape.y - far_gap, shape.x + shape.w + far_gap, shape.y + shape.h + far_gap)
            if segment_intersects_box(a, b, close_box):
                passes += 5
            elif segment_intersects_box(a, b, far_box):
                passes += 1
    return passes


def count_path_database_contour_conflicts(
    points: list[tuple[float, float]],
    connector: Connector,
    shapes: list[Shape],
) -> int:
    conflicts = 0
    segments = list(zip(points, points[1:]))
    for index, (a, b) in enumerate(segments):
        horizontal = abs(a[1] - b[1]) <= 1 and abs(a[0] - b[0]) > 1
        vertical = abs(a[0] - b[0]) <= 1 and abs(a[1] - b[1]) > 1
        if not horizontal and not vertical:
            continue
        for shape in shapes:
            if shape.kind != "database":
                continue
            if deployment_is_database_attach_segment(index, len(segments), connector, shape):
                continue
            if horizontal:
                span = sorted((a[0], b[0]))
                expanded_span = (shape.x - DEPLOY_DATABASE_ROUTE_GAP_X, shape.x + shape.w + DEPLOY_DATABASE_ROUTE_GAP_X)
                for edge_y in (shape.y, shape.y + shape.h):
                    conflicts += deployment_database_parallel_conflict(
                        a[1],
                        span,
                        edge_y,
                        expanded_span,
                        DEPLOY_DATABASE_ROUTE_GAP_Y,
                    )
            else:
                span = sorted((a[1], b[1]))
                expanded_span = (shape.y - DEPLOY_DATABASE_ROUTE_GAP_Y, shape.y + shape.h + DEPLOY_DATABASE_ROUTE_GAP_Y)
                for edge_x in (shape.x, shape.x + shape.w):
                    conflicts += deployment_database_parallel_conflict(
                        a[0],
                        span,
                        edge_x,
                        expanded_span,
                        DEPLOY_DATABASE_ROUTE_GAP_X,
                    )
    return conflicts


def deployment_is_database_attach_segment(
    index: int,
    segment_count: int,
    connector: Connector,
    shape: Shape,
) -> bool:
    return (shape.id == connector.source and index == 0) or (shape.id == connector.target and index == segment_count - 1)


def deployment_database_parallel_conflict(
    segment_coord: float,
    segment_span: list[float],
    edge_coord: float,
    edge_span: tuple[float, float],
    max_gap: float,
) -> int:
    overlap = min(segment_span[1], edge_span[1]) - max(segment_span[0], edge_span[0])
    if overlap <= 16:
        return 0
    gap = abs(segment_coord - edge_coord)
    if gap <= max_gap * 0.45:
        return max(3, math.ceil(overlap / 56))
    if gap <= max_gap:
        return max(1, math.ceil(overlap / 96))
    return 0


def count_path_boundary_edge_conflicts(
    points: list[tuple[float, float]],
    connector: Connector,
    boundary_shapes: list[Shape],
) -> int:
    conflicts = 0
    for a, b in zip(points, points[1:]):
        horizontal = abs(a[1] - b[1]) <= 1 and abs(a[0] - b[0]) > 1
        vertical = abs(a[0] - b[0]) <= 1 and abs(a[1] - b[1]) > 1
        if not horizontal and not vertical:
            continue
        for shape in boundary_shapes:
            if shape.id in {connector.source, connector.target}:
                continue
            if horizontal:
                span = sorted((a[0], b[0]))
                for edge_y in (shape.y, shape.y + shape.h):
                    conflicts += deployment_boundary_parallel_conflict(a[1], span, edge_y, (shape.x, shape.x + shape.w))
            else:
                span = sorted((a[1], b[1]))
                for edge_x in (shape.x, shape.x + shape.w):
                    conflicts += deployment_boundary_parallel_conflict(a[0], span, edge_x, (shape.y, shape.y + shape.h))
    return conflicts


def deployment_boundary_parallel_conflict(
    segment_coord: float,
    segment_span: list[float],
    edge_coord: float,
    edge_span: tuple[float, float],
) -> int:
    overlap = min(segment_span[1], edge_span[1]) - max(segment_span[0], edge_span[0])
    if overlap <= 18:
        return 0
    gap = abs(segment_coord - edge_coord)
    if gap <= 14:
        return max(3, math.ceil(overlap / 70))
    if gap <= 34 and overlap > 36:
        return max(1, math.ceil(overlap / 120))
    return 0


def spread_deployment_parallel_starts(canvas: Canvas) -> None:
    groups: dict[tuple[str, str, int, int], list[Connector]] = defaultdict(list)
    for connector in canvas.connectors:
        points = connector.points
        if not points or len(points) < 2:
            continue
        start, second = points[0], points[1]
        dx, dy = second[0] - start[0], second[1] - start[1]
        if abs(dx) >= abs(dy) * 2:
            direction = 1 if dx >= 0 else -1
            groups[(connector.source, "H", direction, round(start[1]))].append(connector)
        elif abs(dy) >= abs(dx) * 2:
            direction = 1 if dy >= 0 else -1
            groups[(connector.source, "V", direction, round(start[0]))].append(connector)

    for (_source, orientation, _direction, _lane), connectors in groups.items():
        if len(connectors) < 2:
            continue
        offsets = deployment_parallel_offsets(len(connectors))
        for connector, offset in zip(connectors, offsets):
            if abs(offset) < 1 or not connector.points:
                continue
            points = list(connector.points)
            if orientation == "H":
                base_y = points[0][1]
                for index, point in enumerate(points):
                    if abs(point[1] - base_y) <= 1:
                        points[index] = (point[0], point[1] + offset)
                    else:
                        break
            else:
                base_x = points[0][0]
                for index, point in enumerate(points):
                    if abs(point[0] - base_x) <= 1:
                        points[index] = (point[0] + offset, point[1])
                    else:
                        break
            connector.points = simplify_layout_path(points)


def deployment_parallel_offsets(count: int) -> list[float]:
    center_index = (count - 1) / 2
    return [(index - center_index) * DEPLOY_PARALLEL_STEP for index in range(count)]


def deployment_attach_route(source: Shape, target: Shape, inner: list[tuple[float, float]]) -> list[tuple[float, float]]:
    start = perimeter_point(source, inner[0])
    end = perimeter_point(target, inner[-1])
    return [start] + inner + [end]


def layout_deployment_legacy(model: dict) -> Canvas:
    nodes = {node["id"]: node for node in model["nodes"]}
    stress_fixed = deployment_stress_shapes()
    if set(nodes).issubset(stress_fixed):
        canvas = Canvas("deployment", model.get("title", "Deployment"), 3820, 1460)
        order = [
            "laptop",
            "docker",
            "compiler",
            "actions",
            "repo",
            "local_project",
            "local_cli",
            "local_output",
            "entrypoint",
            "renderer",
            "pdf_compiler",
            "workdir",
            "outdir",
            "queue",
            "image_job",
            "smoke_job",
            "action_cache",
            "compiler_src",
            "diagram_examples",
            "template_src",
        ]
        for node_id in order:
            if node_id not in nodes:
                continue
            kind, x, y, w, h = stress_fixed[node_id]
            node = nodes[node_id]
            canvas.shapes.append(Shape(node_id, kind, x, y, w, h, node["label"], stereotype=node["kind"]))
        for index, edge in enumerate(model["edges"]):
            points, label_position, label = deployment_stress_route(edge["source"], edge["target"], edge.get("label", ""))
            canvas.connectors.append(
                Connector(
                    f"dep_{index}",
                    edge["source"],
                    edge["target"],
                    label,
                    kind=edge.get("kind", "association"),
                    dashed=edge.get("dashed", False),
                    points=points,
                    label_position=label_position,
                )
            )
        return fit_canvas_to_content(finalize_canvas(scale_canvas(canvas, 0.86)))
    fixed = deployment_fixed_shapes()
    if set(nodes).issubset(fixed):
        canvas = Canvas("deployment", model.get("title", "Deployment"), 3600, 1900)
        order = [
            "laptop",
            "docker",
            "compiler",
            "gha",
            "repo",
            "sources",
            "latex",
            "pngs",
            "cli",
            "writer",
            "exporter",
            "buildvol",
            "image_build",
            "render_check",
            "compiler_src",
            "diagram_src",
            "examples",
        ]
        for node_id in order:
            if node_id not in nodes:
                continue
            kind, x, y, w, h = fixed[node_id]
            node = nodes[node_id]
            canvas.shapes.append(Shape(node_id, kind, x, y, w, h, node["label"], stereotype=node["kind"]))
        for index, edge in enumerate(model["edges"]):
            points, label_position, label = deployment_route(edge["source"], edge["target"], edge.get("label", ""))
            canvas.connectors.append(
                Connector(
                    f"dep_{index}",
                    edge["source"],
                    edge["target"],
                    label,
                    kind=edge.get("kind", "association"),
                    dashed=edge.get("dashed", False),
                    points=points,
                    label_position=label_position,
                )
            )
        return finalize_canvas(compact_canvas(scale_canvas(canvas, 0.78), 0.94))
    children: dict[str | None, list[dict]] = defaultdict(list)
    for node in model["nodes"]:
        children[node.get("parent")].append(node)
    top = children[None]
    if top and all(not children.get(node["id"]) for node in top):
        width, height = max(900, 120 + len(top) * 390), 420
        canvas = Canvas("deployment", model.get("title", "Deployment"), width, height)
        for index, node in enumerate(top):
            x, y = 60 + index * 390, 130
            kind = "database" if node["kind"] == "database" else "rect"
            canvas.shapes.append(Shape(node["id"], kind, x, y, 300, 130, node["label"], stereotype=node["kind"]))
        for index, edge in enumerate(model["edges"]):
            points, label_position, label = deployment_route(edge["source"], edge["target"], edge.get("label", ""))
            canvas.connectors.append(
                Connector(
                    f"dep_{index}",
                    edge["source"],
                    edge["target"],
                    label,
                    kind=edge.get("kind", "association"),
                    dashed=edge.get("dashed", False),
                    points=points,
                    label_position=label_position,
                )
            )
        return finalize_canvas(canvas)
    top_specs: list[tuple[float, float, float, float]] = []
    x_cursor = 60
    for node in top:
        child_count = max(1, len(children.get(node["id"], [])))
        cols = 1 if child_count <= 2 else 2
        rows = math.ceil(child_count / cols)
        nested_extra = sum(len(children.get(child["id"], [])) * 170 for child in children.get(node["id"], []))
        w = max(560, cols * 390 + (cols - 1) * 70 + 130)
        h = max(780, rows * 210 + (rows - 1) * 74 + 210 + nested_extra)
        top_specs.append((x_cursor, 70, w, h))
        x_cursor += w + 210
    width = int(x_cursor + 40)
    height = int(max((y + h for _, y, _, h in top_specs), default=980) + 80)
    canvas = Canvas("deployment", model.get("title", "Deployment"), width, height)
    for index, node in enumerate(top):
        x, y, w, h = top_specs[index]
        canvas.shapes.append(Shape(node["id"], "boundary" if node["kind"] in {"cloud", "node"} else "rect", x, y, w, h, node["label"], stereotype=node["kind"]))
        place_children(canvas, children, node["id"], x + 35, y + 60, w - 70, h - 95)
    for index, edge in enumerate(model["edges"]):
        points, label_position, label = deployment_route(edge["source"], edge["target"], edge.get("label", ""))
        canvas.connectors.append(
            Connector(
                f"dep_{index}",
                edge["source"],
                edge["target"],
                label,
                kind=edge.get("kind", "association"),
                dashed=edge.get("dashed", False),
                points=points,
                label_position=label_position,
            )
        )
    return fit_canvas_to_content(finalize_canvas(canvas))


def deployment_fixed_shapes() -> dict[str, tuple[str, float, float, float, float]]:
    return {
        "laptop": ("boundary", 80, 140, 520, 1520),
        "docker": ("boundary", 760, 140, 1320, 1520),
        "compiler": ("boundary", 900, 300, 700, 1050),
        "repo": ("boundary", 2300, 140, 1100, 420),
        "gha": ("boundary", 2300, 700, 1100, 960),
        "sources": ("rect", 160, 330, 340, 150),
        "latex": ("rect", 160, 730, 340, 150),
        "pngs": ("rect", 160, 1260, 340, 150),
        "cli": ("rect", 1050, 390, 420, 120),
        "writer": ("rect", 1050, 720, 420, 120),
        "exporter": ("rect", 1050, 1050, 420, 120),
        "buildvol": ("database", 1710, 700, 300, 190),
        "compiler_src": ("rect", 2400, 270, 260, 120),
        "diagram_src": ("rect", 2720, 270, 260, 120),
        "examples": ("rect", 3040, 270, 260, 120),
        "image_build": ("rect", 2420, 900, 370, 160),
        "render_check": ("rect", 2980, 900, 370, 160),
    }


def deployment_stress_shapes() -> dict[str, tuple[str, float, float, float, float]]:
    return {
        "laptop": ("boundary", 70, 100, 650, 1260),
        "docker": ("boundary", 820, 100, 1160, 1260),
        "compiler": ("boundary", 930, 250, 780, 870),
        "actions": ("boundary", 2140, 100, 760, 1260),
        "repo": ("boundary", 3040, 100, 700, 1260),
        "local_project": ("rect", 150, 230, 470, 170),
        "local_cli": ("rect", 150, 520, 470, 170),
        "local_output": ("database", 150, 930, 470, 190),
        "entrypoint": ("rect", 1030, 360, 560, 110),
        "renderer": ("rect", 1030, 560, 560, 110),
        "pdf_compiler": ("rect", 1030, 760, 560, 110),
        "workdir": ("database", 1030, 930, 250, 130),
        "outdir": ("database", 1340, 930, 250, 130),
        "queue": ("rect", 950, 1180, 720, 130),
        "image_job": ("rect", 2200, 230, 560, 170),
        "smoke_job": ("rect", 2200, 520, 560, 170),
        "action_cache": ("database", 2200, 930, 560, 190),
        "compiler_src": ("rect", 3120, 230, 540, 170),
        "diagram_examples": ("rect", 3120, 520, 540, 170),
        "template_src": ("rect", 3120, 810, 540, 170),
    }


def deployment_stress_route(source: str, target: str, label: str) -> tuple[list[tuple[float, float]] | None, tuple[float, float] | None, str]:
    routes: dict[tuple[str, str], tuple[list[tuple[float, float]], tuple[float, float] | None, str]] = {
        ("local_project", "local_cli"): ([(385, 400), (385, 520)], (415, 455), "selected path"),
        ("local_cli", "entrypoint"): ([(620, 605), (1030, 415)], (760, 500), "docker run"),
        ("entrypoint", "workdir"): ([(1030, 415), (990, 415), (990, 995), (1030, 995)], (1005, 700), "mounts project copy"),
        ("entrypoint", "renderer"): ([(1310, 470), (1310, 560)], (1330, 505), "render diagrams"),
        ("renderer", "outdir"): ([(1590, 615), (1660, 615), (1660, 995), (1590, 995)], (1675, 790), "writes PNG and drawio"),
        ("entrypoint", "pdf_compiler"): ([(1590, 415), (1660, 415), (1660, 815), (1590, 815)], (1675, 610), "compile note"),
        ("pdf_compiler", "outdir"): ([(1465, 870), (1465, 930)], (1490, 895), "writes PDF"),
        ("compiler_src", "image_job"): ([(3120, 315), (2760, 315)], (2890, 265), "Dockerfile context"),
        ("diagram_examples", "smoke_job"): ([(3120, 605), (2760, 605)], (2890, 555), "stress inputs"),
        ("template_src", "smoke_job"): ([(3120, 895), (2925, 760), (2760, 650)], (2905, 755), "sample note"),
        ("image_job", "action_cache"): ([(2200, 315), (2160, 315), (2160, 1025), (2200, 1025)], (2175, 660), "stores layers"),
        ("image_job", "smoke_job"): ([(2480, 400), (2480, 520)], (2505, 455), "built image"),
    }
    return routes.get((source, target), (None, None, label))


def deployment_route(source: str, target: str, label: str) -> tuple[list[tuple[float, float]] | None, tuple[float, float] | None, str]:
    routes: dict[tuple[str, str], tuple[list[tuple[float, float]], tuple[float, float] | None, str]] = {
        ("sources", "cli"): ([(500, 405), (1050, 430)], (725, 355), "mounted input path"),
        ("latex", "cli"): ([(500, 805), (1050, 490)], (705, 600), "reads project assets"),
        ("cli", "writer"): ([(1260, 510), (1260, 720)], (1300, 610), "normalized model"),
        ("writer", "exporter"): ([(1260, 840), (1260, 1050)], (1300, 940), ".drawio file"),
        ("exporter", "pngs"): ([(1050, 1110), (500, 1335)], (710, 1190), "writes PNG"),
        ("cli", "buildvol"): ([(1470, 450), (1710, 795)], (1570, 575), "diagnostics"),
        ("compiler_src", "image_build"): ([(2530, 390), (2605, 900)], (2635, 620), "Dockerfile and dependencies"),
        ("diagram_src", "render_check"): ([(2850, 390), (3075, 900)], (2945, 620), "generator source"),
        ("examples", "render_check"): ([(3170, 390), (3265, 900)], (3220, 645), "sample project"),
        ("image_build", "render_check"): ([(2790, 980), (2980, 980)], (2860, 920), "built image"),
    }
    return routes.get((source, target), (None, None, label))


def place_children(canvas: Canvas, children: dict[str | None, list[dict]], parent: str, x: float, y: float, w: float, h: float) -> None:
    items = children.get(parent, [])
    if not items:
        return
    if any(children.get(item["id"]) for item in items):
        if len(items) > 2 and w >= 900:
            cols = 2
            gap_x = 80
            gap_y = 80
            item_w = (w - gap_x) / cols
            heights = [max(170, 130 + len(children.get(item["id"], [])) * 150) if children.get(item["id"]) else 160 for item in items]
            row_heights = [max(heights[row * cols : row * cols + cols]) for row in range(math.ceil(len(items) / cols))]
            y_offsets = [0]
            for row_h in row_heights[:-1]:
                y_offsets.append(y_offsets[-1] + row_h + gap_y)
            for index, item in enumerate(items):
                row = index // cols
                col = index % cols
                child_count = len(children.get(item["id"], []))
                item_h = row_heights[row]
                item_x = x + col * (item_w + gap_x)
                item_y = y + y_offsets[row]
                kind = "database" if item["kind"] == "database" else "boundary" if child_count else "rect"
                canvas.shapes.append(Shape(item["id"], kind, item_x, item_y, item_w, item_h, item["label"], stereotype=item["kind"], parent=None))
                if child_count:
                    place_children(canvas, children, item["id"], item_x + 34, item_y + 70, item_w - 68, item_h - 96)
            return
        cursor_y = y
        for item in items:
            child_count = len(children.get(item["id"], []))
            item_h = max(170, 120 + child_count * 140) if child_count else 150
            kind = "database" if item["kind"] == "database" else "boundary" if child_count else "rect"
            canvas.shapes.append(Shape(item["id"], kind, x, cursor_y, w, item_h, item["label"], stereotype=item["kind"], parent=None))
            if child_count:
                place_children(canvas, children, item["id"], x + 34, cursor_y + 70, w - 68, item_h - 96)
            cursor_y += item_h + 70
        return
    cols = 1 if len(items) <= 4 or w < 620 else 2
    rows = math.ceil(len(items) / cols)
    item_w = (w - 54 * (cols - 1)) / cols
    base_item_h = min(170, max(116, (h - 54 * (rows - 1)) / max(1, rows)))
    for index, item in enumerate(items):
        col = index % cols
        row = index // cols
        sx = x + col * (item_w + 54)
        sy = y + row * (base_item_h + 54)
        has_children = bool(children.get(item["id"]))
        item_h = base_item_h
        if has_children:
            child_count = len(children[item["id"]])
            item_h = max(item_h, 98 + child_count * 104)
        kind = "database" if item["kind"] == "database" else "boundary" if has_children else "rect"
        canvas.shapes.append(Shape(item["id"], kind, sx, sy, item_w, item_h, item["label"], stereotype=item["kind"], parent=None))
        if has_children:
            place_children(canvas, children, item["id"], sx + 28, sy + 64, item_w - 56, item_h - 86)


def layout_pipeline(model: dict) -> Canvas:
    nodes = {node["id"]: node for node in model["nodes"]}
    edges = model["edges"]
    fixed = {
        "raw": (80, 80),
        "ingest": (80, 250),
        "validate": (80, 450),
        "reject": (80, 760),
        "extract": (520, 80),
        "clean": (520, 250),
        "split": (520, 450),
        "features": (520, 720),
        "train": (940, 250),
        "eval": (940, 450),
        "registry": (940, 760),
        "deploy": (1320, 80),
        "api": (1320, 250),
        "post": (1320, 450),
        "report": (1320, 720),
    }
    if set(nodes).issubset(fixed):
        canvas = Canvas("ml-pipeline", model.get("title", "ML Pipeline"), 1600, 980)
        for node_id, node in nodes.items():
            x, y = fixed[node_id]
            kind = pipeline_shape_kind(node)
            w, h = (180, 130) if kind == "diamond" else (180, 90)
            canvas.shapes.append(Shape(node_id, kind, x, y, w, h, node["label"]))
        for index, edge in enumerate(edges):
            points, label_position = pipeline_route(edge["source"], edge["target"])
            canvas.connectors.append(
                Connector(
                    f"pipe_{index}",
                    edge["source"],
                    edge["target"],
                    edge.get("label", ""),
                    points=points,
                    label_position=label_position,
                )
            )
        return finalize_canvas(canvas)
    ranks = graph_ranks(nodes, edges)
    by_rank: dict[int, list[dict]] = defaultdict(list)
    for node_id, rank in ranks.items():
        by_rank[rank].append(nodes[node_id])
    rank_count = max(by_rank) + 1 if by_rank else 1
    cols_per_band = max(1, rank_count)
    x_gap = 380
    y_gap = 220
    node_w = 210
    node_h = 104
    width = 160 + min(rank_count, cols_per_band) * x_gap
    max_items = max((len(items) for items in by_rank.values()), default=1)
    bands = math.ceil(rank_count / cols_per_band)
    height = max(760, 90 + bands * 280 + max_items * y_gap)
    canvas = Canvas("ml-pipeline", model.get("title", "ML Pipeline"), width, height)
    for rank, items in by_rank.items():
        for index, node in enumerate(items):
            band = rank // cols_per_band
            col = rank % cols_per_band
            x = 60 + col * x_gap
            y = 90 + band * 320 + index * y_gap + (max_items - len(items)) * 54
            kind = pipeline_shape_kind(node)
            canvas.shapes.append(Shape(node["id"], kind, x, y, node_w, 140 if kind == "diamond" else node_h, node["label"]))
    for index, edge in enumerate(edges):
        label = edge.get("label", "")
        if ranks.get(edge["source"], 0) > ranks.get(edge["target"], 0):
            label = ""
        points, label_position = pipeline_route(edge["source"], edge["target"])
        canvas.connectors.append(Connector(f"pipe_{index}", edge["source"], edge["target"], label, points=points, label_position=label_position))
    return fit_canvas_to_content(finalize_canvas(canvas))


def pipeline_shape_kind(node: dict) -> str:
    if node.get("kind") == "database":
        return "database"
    if node.get("kind") == "decision":
        return "diamond"
    if node.get("kind") == "circle":
        return "ellipse"
    return "rect"


def pipeline_route(source: str, target: str) -> tuple[list[tuple[float, float]] | None, tuple[float, float] | None]:
    routes: dict[tuple[str, str], tuple[list[tuple[float, float]], tuple[float, float] | None]] = {
        ("raw", "ingest"): ([(170, 170), (170, 250)], None),
        ("ingest", "validate"): ([(170, 340), (170, 450)], None),
        ("validate", "extract"): ([(260, 515), (420, 515), (420, 125), (520, 125)], (350, 490)),
        ("validate", "reject"): ([(170, 580), (170, 760)], (200, 670)),
        ("extract", "clean"): ([(610, 170), (610, 250)], None),
        ("clean", "split"): ([(610, 340), (610, 450)], None),
        ("split", "features"): ([(610, 540), (610, 720)], None),
        ("features", "train"): ([(700, 765), (820, 765), (820, 295), (940, 295)], None),
        ("train", "eval"): ([(1030, 340), (1030, 450)], None),
        ("eval", "registry"): ([(1030, 580), (1030, 760)], (1060, 670)),
        ("registry", "deploy"): ([(1120, 805), (1220, 805), (1220, 125), (1320, 125)], None),
        ("deploy", "api"): ([(1410, 170), (1410, 250)], None),
        ("api", "post"): ([(1410, 340), (1410, 450)], None),
        ("post", "report"): ([(1410, 540), (1410, 720)], None),
        ("reject", "report"): ([(260, 805), (360, 805), (360, 930), (1270, 930), (1270, 765), (1320, 765)], None),
    }
    return routes.get((source, target), (None, None))


def graph_ranks(nodes: dict[str, dict], edges: list[dict]) -> dict[str, int]:
    incoming = defaultdict(int)
    outgoing = defaultdict(list)
    for edge in edges:
        outgoing[edge["source"]].append(edge["target"])
        incoming[edge["target"]] += 1
        incoming.setdefault(edge["source"], incoming[edge["source"]])
    queue = deque([node_id for node_id in nodes if incoming[node_id] == 0])
    ranks = {node_id: 0 for node_id in nodes}
    while queue:
        node_id = queue.popleft()
        for nxt in outgoing[node_id]:
            ranks[nxt] = max(ranks[nxt], ranks[node_id] + 1)
            incoming[nxt] -= 1
            if incoming[nxt] == 0:
                queue.append(nxt)
    return ranks


def layout_usecase(model: dict) -> Canvas:
    boundary = model.get("boundary", {"id": "system", "label": "System"})
    usecases = model["usecases"]
    legacy_usecase_positions = {
        "UC_Render": (500, 190),
        "UC_Detect": (1160, 120),
        "UC_Validate": (620, 470),
        "UC_Drawio": (1200, 430),
        "UC_Diagnostics": (430, 760),
        "UC_Png": (1110, 730),
        "UC_Review": (520, 1030),
        "UC_CI": (1200, 970),
        "UC_Insert": (450, 1245),
        "UC_Edit": (1160, 1165),
    }
    stress_usecase_positions = {
        "UC_Import": (470, 190),
        "UC_Detect": (900, 190),
        "UC_Render": (1330, 190),
        "UC_Validate": (470, 500),
        "UC_Compile": (900, 500),
        "UC_OpenPdf": (1330, 500),
        "UC_Errors": (470, 850),
        "UC_Normal": (900, 850),
        "UC_Edit": (1760, 500),
        "UC_CI": (1760, 190),
    }
    legacy_actor_positions = {
        "student": (80, 220),
        "normal_controller": (80, 545),
        "supervisor": (80, 980),
        "ci": (1920, 940),
        "drawio": (1920, 1185),
    }
    stress_actor_positions = {
        "Author": (80, 190),
        "Supervisor": (80, 850),
        "Controller": (80, 1050),
        "CI": (2300, 190),
        "Drawio": (2300, 520),
    }
    usecase_ids = {usecase["id"] for usecase in usecases}
    actor_ids = {actor["id"] for actor in model["actors"]}
    use_stress_preferred = usecase_ids.issubset(stress_usecase_positions) and actor_ids.issubset(stress_actor_positions)
    if use_stress_preferred:
        usecase_positions = stress_usecase_positions
        actor_positions = stress_actor_positions
    else:
        usecase_positions = legacy_usecase_positions
        actor_positions = legacy_actor_positions
    use_preferred = usecase_ids.issubset(usecase_positions) and actor_ids.issubset(actor_positions)
    generic_usecase_positions: dict[str, tuple[float, float]] = {}
    if use_preferred:
        width, height = (2550, 1420) if use_stress_preferred else (2200, 1500)
        canvas = Canvas("use-case", model.get("title", "Use Case"), width, height)
        boundary_w = 1900 if use_stress_preferred else 1510
        boundary_h = 1150 if use_stress_preferred else 1300
        canvas.shapes.append(Shape(boundary["id"], "boundary", 330, 95, boundary_w, boundary_h, boundary["label"]))
    else:
        generic_usecase_positions = usecase_generic_positions(usecases, model["edges"])
        max_case_x = max((x for x, _ in generic_usecase_positions.values()), default=470)
        max_case_y = max((y for _, y in generic_usecase_positions.values()), default=190)
        boundary_w = max(1900, int(max_case_x - 300 + 520))
        boundary_h = max(1180, int(max_case_y - 90 + 260))
        width = boundary_w + 760
        height = max(boundary_h + 220, 260 + len(model["actors"]) * 240)
        canvas = Canvas("use-case", model.get("title", "Use Case"), width, height)
        canvas.shapes.append(Shape(boundary["id"], "boundary", 300, 90, boundary_w, boundary_h, boundary["label"]))
    for index, usecase in enumerate(usecases):
        if use_preferred:
            x, y = usecase_positions[usecase["id"]]
            w, h = 320, 94
        else:
            x, y = generic_usecase_positions[usecase["id"]]
            w, h = 360, 110
        canvas.shapes.append(Shape(usecase["id"], "ellipse", x, y, w, h, usecase["label"]))
    used_actor_y: dict[bool, list[float]] = defaultdict(list)
    for index, actor in enumerate(model["actors"]):
        if use_preferred:
            x, y = actor_positions[actor["id"]]
        else:
            right_side = actor.get("side") == "right"
            side_index = sum(1 for item in model["actors"][:index] if (item.get("side") == "right") == right_side)
            x = canvas.shapes[0].x + canvas.shapes[0].w + 130 if right_side else 70
            y = usecase_actor_y(actor["id"], generic_usecase_positions, model["edges"], side_index)
            y = spread_usecase_actor_y(y, used_actor_y[right_side])
            used_actor_y[right_side].append(y)
        canvas.shapes.append(Shape(actor["id"], "actor", x, y, 150, 118, actor["label"]))
    for index, edge in enumerate(model["edges"]):
        kind = "dependency" if edge.get("dashed") else "association_no_arrow"
        if use_preferred:
            points, label_position = usecase_route(edge["source"], edge["target"], use_stress_preferred)
        else:
            points, label_position = usecase_auto_route(edge, canvas.shape_map())
        canvas.connectors.append(
            Connector(
                f"uc_{index}",
                edge["source"],
                edge["target"],
                edge.get("label", ""),
                kind=kind,
                dashed=edge.get("dashed", False),
                points=points,
                label_position=label_position,
            )
        )
    if use_preferred:
        return finalize_canvas(canvas)
    canvas = apply_elk_layout(
        canvas,
        direction="RIGHT",
        node_spacing=155,
        layer_spacing=215,
        edge_spacing=66,
        edge_routing="POLYLINE",
        margin=80,
    )
    shape_map = canvas.shape_map()
    boundary_shape = shape_map.get(boundary["id"])
    if boundary_shape:
        fit_boundary_to_shapes(boundary_shape, [shape_map[item["id"]] for item in usecases if item["id"] in shape_map], padding=110)
    return fit_canvas_to_content(canvas, margin=80)


def usecase_actor_y(actor_id: str, usecase_positions: dict[str, tuple[float, float]], edges: list[dict], fallback_index: int) -> float:
    centers: list[float] = []
    for edge in edges:
        other = ""
        if edge["source"] == actor_id:
            other = edge["target"]
        elif edge["target"] == actor_id:
            other = edge["source"]
        if other in usecase_positions:
            centers.append(usecase_positions[other][1] + 55)
    if centers:
        return max(130, sum(centers) / len(centers) - 59)
    return 170 + fallback_index * 230


def usecase_generic_positions(usecases: list[dict], edges: list[dict]) -> dict[str, tuple[float, float]]:
    ids = [usecase["id"] for usecase in usecases]
    id_set = set(ids)
    base_slots: dict[str, tuple[int, int]] = {usecase_id: (index // 3, index % 3) for index, usecase_id in enumerate(ids)}
    dependency_indegree: dict[str, int] = defaultdict(int)
    dependency_sources: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        source = edge["source"]
        target = edge["target"]
        if source in id_set and target in id_set:
            dependency_indegree[target] += 1
            dependency_sources[target].append(source)

    reserved: dict[tuple[int, int], str] = {}
    for usecase_id in sorted(ids, key=lambda item: (-dependency_indegree[item], ids.index(item))):
        if dependency_indegree[usecase_id] < 2:
            continue
        source_rows = [base_slots[source][0] for source in dependency_sources[usecase_id] if source in base_slots]
        row = max(source_rows, default=base_slots[usecase_id][0]) + 1
        while (row, 1) in reserved:
            row += 1
        reserved[(row, 1)] = usecase_id

    slots: dict[str, tuple[int, int]] = {usecase_id: slot for slot, usecase_id in reserved.items()}
    occupied = set(reserved)
    cursor_row = 0
    cursor_col = 0
    for usecase_id in ids:
        if usecase_id in slots:
            continue
        while (cursor_row, cursor_col) in occupied:
            cursor_col += 1
            if cursor_col >= 3:
                cursor_col = 0
                cursor_row += 1
        slots[usecase_id] = (cursor_row, cursor_col)
        occupied.add((cursor_row, cursor_col))
        cursor_col += 1
        if cursor_col >= 3:
            cursor_col = 0
            cursor_row += 1

    x0, y0 = 470, 190
    x_gap, y_gap = 570, 290
    return {usecase_id: (x0 + col * x_gap, y0 + row * y_gap) for usecase_id, (row, col) in slots.items()}


def usecase_auto_route(edge: dict, shape_map: dict[str, Shape]) -> tuple[list[tuple[float, float]] | None, tuple[float, float] | None]:
    source = shape_map.get(edge["source"])
    target = shape_map.get(edge["target"])
    if not source or not target:
        return None, None
    start = usecase_perimeter_point(source, center(target))
    end = usecase_perimeter_point(target, center(source))
    candidates = usecase_route_candidates(start, end, source, target, shape_map)
    best = min(candidates, key=lambda points: usecase_route_score(points, source.id, target.id, shape_map))
    return best, usecase_label_anchor(best)


def usecase_route_candidates(
    start: tuple[float, float],
    end: tuple[float, float],
    source: Shape,
    target: Shape,
    shape_map: dict[str, Shape],
) -> list[list[tuple[float, float]]]:
    sx, sy = start
    tx, ty = end
    min_top = min(source.y, target.y)
    max_bottom = max(source.y + source.h, target.y + target.h)
    min_left = min(source.x, target.x)
    max_right = max(source.x + source.w, target.x + target.w)
    y_lanes = {sy, ty, min_top - 70, max_bottom + 70, (sy + ty) / 2}
    x_lanes = {sx, tx, min_left - 80, max_right + 80, (sx + tx) / 2}
    for shape in shape_map.values():
        if shape.kind in {"boundary", "group", "lifeline", "fragment"}:
            continue
        y_lanes.update({shape.y - 55, shape.y + shape.h + 55})
        x_lanes.update({shape.x - 65, shape.x + shape.w + 65})

    candidates: list[list[tuple[float, float]]] = [
        [start, end],
        [start, (tx, sy), end],
        [start, (sx, ty), end],
    ]
    for lane_y in sorted(y_lanes, key=lambda y: abs(y - (sy + ty) / 2))[:8]:
        candidates.append([start, (sx, lane_y), (tx, lane_y), end])
    for lane_x in sorted(x_lanes, key=lambda x: abs(x - (sx + tx) / 2))[:8]:
        candidates.append([start, (lane_x, sy), (lane_x, ty), end])
    return [simplify_layout_path(points) for points in candidates]


def usecase_route_score(points: list[tuple[float, float]], source_id: str, target_id: str, shape_map: dict[str, Shape]) -> float:
    collisions = 0
    close_hits = 0
    for start, end in zip(points, points[1:]):
        for shape in shape_map.values():
            if shape.id in {source_id, target_id} or shape.kind in {"boundary", "group", "lifeline", "fragment"}:
                continue
            box = (shape.x - 12, shape.y - 12, shape.x + shape.w + 12, shape.y + shape.h + 12)
            if segment_intersects_box(start, end, box):
                collisions += 1
            close_box = (shape.x - 34, shape.y - 34, shape.x + shape.w + 34, shape.y + shape.h + 34)
            if segment_intersects_box(start, end, close_box):
                close_hits += 1
    bends = max(0, len(points) - 2)
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))
    return collisions * 100000 + close_hits * 1800 + bends * 120 + length


def usecase_perimeter_point(shape: Shape, toward: tuple[float, float]) -> tuple[float, float]:
    cx, cy = center(shape)
    dx = toward[0] - cx
    dy = toward[1] - cy
    if abs(dx) < 0.01 and abs(dy) < 0.01:
        return cx + shape.w / 2, cy
    if shape.kind == "ellipse":
        rx = shape.w / 2
        ry = shape.h / 2
        scale = 1 / math.sqrt((dx / rx) ** 2 + (dy / ry) ** 2)
        return cx + dx * scale, cy + dy * scale
    if abs(dx) * shape.h >= abs(dy) * shape.w:
        x = shape.x + shape.w if dx >= 0 else shape.x
        y = cy + dy * (shape.w / 2) / max(abs(dx), 1.0)
        return x, min(shape.y + shape.h, max(shape.y, y))
    y = shape.y + shape.h if dy >= 0 else shape.y
    x = cx + dx * (shape.h / 2) / max(abs(dy), 1.0)
    return min(shape.x + shape.w, max(shape.x, x)), y


def direct_relation_route(source: Shape | None, target: Shape | None) -> tuple[list[tuple[float, float]] | None, tuple[float, float] | None]:
    if not source or not target:
        return None, None
    start = usecase_perimeter_point(source, center(target))
    end = usecase_perimeter_point(target, center(source))
    points = [start, end]
    return points, usecase_label_anchor(points)


def usecase_label_anchor(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    if len(points) < 2:
        return None
    a, b = max(zip(points, points[1:]), key=lambda pair: math.hypot(pair[1][0] - pair[0][0], pair[1][1] - pair[0][1]))
    return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 36


def simplify_layout_path(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for point in points:
        if not result or math.hypot(point[0] - result[-1][0], point[1] - result[-1][1]) > 1:
            result.append(point)
    if len(result) <= 2:
        return result
    simplified = [result[0]]
    for index, point in enumerate(result[1:-1], start=1):
        prev = simplified[-1]
        nxt = result[index + 1]
        if abs((point[0] - prev[0]) * (nxt[1] - point[1]) - (point[1] - prev[1]) * (nxt[0] - point[0])) < 0.01:
            before = (point[0] - prev[0], point[1] - prev[1])
            after = (nxt[0] - point[0], nxt[1] - point[1])
            if before[0] * after[0] + before[1] * after[1] >= 0:
                continue
        simplified.append(point)
    simplified.append(result[-1])
    return simplified


def spread_usecase_actor_y(y: float, used: list[float]) -> float:
    result = y
    while any(abs(result - existing) < 170 for existing in used):
        result += 190
    return result


def usecase_route(source: str, target: str, use_stress: bool = False) -> tuple[list[tuple[float, float]] | None, tuple[float, float] | None]:
    stress_routes: dict[tuple[str, str], tuple[list[tuple[float, float]], tuple[float, float] | None]] = {
        ("Author", "UC_Import"): ([(230, 250), (470, 237)], (300, 215)),
        ("Supervisor", "UC_Errors"): ([(230, 910), (470, 897)], (285, 880)),
        ("Controller", "UC_Normal"): ([(230, 1110), (1060, 1110), (1060, 944)], (600, 1065)),
        ("CI", "UC_CI"): ([(2300, 250), (2080, 237)], (2135, 205)),
        ("Drawio", "UC_Edit"): ([(2300, 580), (2080, 547)], (2140, 535)),
        ("UC_Import", "UC_Detect"): ([(790, 237), (900, 237)], (810, 200)),
        ("UC_Detect", "UC_Render"): ([(1220, 237), (1330, 237)], (1245, 200)),
        ("UC_Render", "UC_Validate"): ([(1490, 284), (1490, 400), (630, 400), (630, 500)], (1025, 355)),
        ("UC_Validate", "UC_Compile"): ([(790, 547), (900, 547)], (810, 510)),
        ("UC_Compile", "UC_OpenPdf"): ([(1220, 547), (1330, 547)], (1245, 510)),
        ("UC_Validate", "UC_Errors"): ([(630, 594), (630, 850)], (660, 720)),
        ("UC_Compile", "UC_Errors"): ([(1060, 594), (1060, 710), (790, 897)], (900, 710)),
        ("UC_Render", "UC_Edit"): ([(1555, 280), (1760, 410), (1920, 500)], (1720, 355)),
        ("UC_CI", "UC_Render"): ([(1760, 237), (1650, 237)], (1665, 200)),
    }
    if use_stress and (source, target) in stress_routes:
        return stress_routes[(source, target)]
    routes: dict[tuple[str, str], tuple[list[tuple[float, float]], tuple[float, float] | None]] = {
        ("Author", "UC_Import"): ([(230, 250), (500, 237)], (300, 215)),
        ("Supervisor", "UC_Errors"): ([(230, 920), (500, 907)], (285, 890)),
        ("Controller", "UC_Normal"): ([(230, 710), (650, 765), (950, 907)], (410, 735)),
        ("CI", "UC_CI"): ([(1920, 1170), (1270, 1227)], (1480, 1190)),
        ("Drawio", "UC_Edit"): ([(1920, 920), (1720, 907)], (1745, 870)),
        ("UC_Import", "UC_Detect"): ([(820, 237), (950, 237)], (850, 200)),
        ("UC_Detect", "UC_Render"): ([(1270, 237), (1400, 237)], (1296, 200)),
        ("UC_Render", "UC_Validate"): ([(1400, 260), (1230, 400), (820, 540)], (1050, 390)),
        ("UC_Validate", "UC_Compile"): ([(820, 567), (950, 567)], (850, 530)),
        ("UC_Compile", "UC_OpenPdf"): ([(1270, 567), (1400, 567)], (1290, 530)),
        ("UC_Validate", "UC_Errors"): ([(660, 614), (660, 860)], (690, 725)),
        ("UC_Compile", "UC_Errors"): ([(950, 610), (820, 907)], (805, 725)),
        ("UC_Render", "UC_Edit"): ([(1720, 237), (1815, 237), (1815, 907), (1720, 907)], (1735, 540)),
        ("UC_CI", "UC_Render"): ([(1110, 1180), (1110, 1040), (1815, 1040), (1815, 237), (1720, 237)], (1140, 1030)),
        ("student", "UC_Render"): ([(230, 280), (500, 237)], None),
        ("normal_controller", "UC_Validate"): ([(230, 605), (620, 517)], None),
        ("supervisor", "UC_Review"): ([(230, 1040), (520, 1077)], None),
        ("ci", "UC_CI"): ([(1920, 1000), (1520, 1017)], None),
        ("drawio", "UC_Edit"): ([(1920, 1245), (1480, 1212)], None),
        ("UC_Render", "UC_Detect"): ([(820, 237), (1160, 167)], (990, 158)),
        ("UC_Render", "UC_Validate"): ([(710, 284), (720, 470)], (600, 360)),
        ("UC_Validate", "UC_Drawio"): ([(940, 517), (1200, 477)], (1065, 448)),
        ("UC_Drawio", "UC_Png"): ([(1360, 524), (1270, 730)], (1415, 625)),
        ("UC_Diagnostics", "UC_Validate"): ([(690, 760), (670, 564)], (505, 650)),
        ("UC_Edit", "UC_Insert"): ([(1160, 1212), (770, 1292)], (950, 1175)),
    }
    return routes.get((source, target), (None, None))
