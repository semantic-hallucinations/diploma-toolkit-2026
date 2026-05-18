from __future__ import annotations

from dataclasses import dataclass
import heapq
import math

from .rendering import (
    Canvas,
    Connector,
    Shape,
    boxes_intersect,
    connector_points,
    expanded_box,
    label_obstacle_boxes,
)


Point = tuple[float, float]
Box = tuple[float, float, float, float]


NON_OBSTACLE_KINDS = {"boundary", "group", "lifeline", "fragment"}


@dataclass(frozen=True)
class RoutedPath:
    points: list[Point]
    score: float
    blocked_segments: int


def route_unrouted_connectors(canvas: Canvas) -> Canvas:
    """Assign explicit routes to connectors that still rely on renderer fallback."""
    shape_map = canvas.shape_map()
    routed_segments: list[tuple[Point, Point]] = []
    used_ports: dict[str, list[Point]] = {}

    for connector in canvas.connectors:
        points = connector_points(connector, shape_map)
        if len(points) >= 2:
            routed_segments.extend(zip(points, points[1:]))
            if connector.source in shape_map:
                used_ports.setdefault(connector.source, []).append(points[0])
            if connector.target in shape_map:
                used_ports.setdefault(connector.target, []).append(points[-1])

    pending = [connector for connector in canvas.connectors if not connector.points]
    pending.sort(key=lambda connector: connector_route_priority(connector, shape_map))
    for connector in pending:
        source = shape_map.get(connector.source)
        target = shape_map.get(connector.target)
        if not source or not target:
            continue
        margin = obstacle_margin(canvas.profile)
        obstacles = [
            expanded_shape_box(shape, margin)
            for shape in canvas.shapes
            if shape.id not in {connector.source, connector.target} and shape.kind not in NON_OBSTACLE_KINDS
        ]
        for shape in canvas.shapes:
            if shape.id not in {connector.source, connector.target}:
                obstacles.extend(expanded_box(box, 10) for box in label_obstacle_boxes(shape))
        path = route_between_shapes(
            source,
            target,
            obstacles,
            routed_segments,
            used_ports,
            label=connector.label,
            canvas_size=(canvas.width, canvas.height),
        )
        connector.points = path.points
        routed_segments.extend(zip(path.points, path.points[1:]))
        used_ports.setdefault(connector.source, []).append(path.points[0])
        used_ports.setdefault(connector.target, []).append(path.points[-1])

    expand_canvas_to_routes(canvas)
    return canvas


def connector_route_priority(connector: Connector, shape_map: dict[str, Shape]) -> tuple[int, float, str]:
    source = shape_map.get(connector.source)
    target = shape_map.get(connector.target)
    if not source or not target:
        return (9, float("inf"), connector.id)
    external_count = sum(1 for shape in (source, target) if shape.kind == "actor" or shape.stereotype == "External")
    relation_priority = 0 if external_count == 0 else 1 if external_count == 1 else 2
    return (relation_priority, distance(center(source), center(target)), connector.id)


def route_between_shapes(
    source: Shape,
    target: Shape,
    obstacles: list[Box],
    routed_segments: list[tuple[Point, Point]],
    used_ports: dict[str, list[Point]],
    *,
    label: str,
    canvas_size: tuple[int, int],
) -> RoutedPath:
    source_ports = port_candidates(source, target)
    target_ports = port_candidates(target, source)
    paths: list[RoutedPath] = []
    label_boxes = label_obstacles(source, target, obstacles)
    port_pairs = sorted(
        ((start, end) for start in source_ports for end in target_ports),
        key=lambda pair: distance(pair[0], pair[1])
        + min_port_distance(pair[0], used_ports.get(source.id, [])) * 8
        + min_port_distance(pair[1], used_ports.get(target.id, [])) * 8,
    )
    for start, end in port_pairs[:36]:
        for points in candidate_paths(start, end, obstacles, canvas_size):
            simplified = simplify_path(points)
            if len(simplified) < 2:
                continue
            paths.append(
                score_path(
                    simplified,
                    obstacles,
                    routed_segments,
                    used_ports.get(source.id, []),
                    used_ports.get(target.id, []),
                    label=label,
                    label_obstacles=label_boxes,
                    check_label=False,
                    canvas_size=canvas_size,
                    source=source,
                    target=target,
                )
            )
    paths = rescore_label_candidates(
        paths,
        obstacles,
        routed_segments,
        used_ports.get(source.id, []),
        used_ports.get(target.id, []),
        label,
        label_boxes,
        canvas_size,
        source,
        target,
    )
    if paths and min(path.blocked_segments for path in paths) == 0:
        return min(paths, key=lambda item: item.score)
    for start, end in port_pairs[:28]:
        grid_candidate = grid_route(start, end, obstacles, routed_segments, canvas_size)
        if not grid_candidate:
            continue
        simplified = simplify_path(grid_candidate)
        if len(simplified) < 2:
            continue
        paths.append(
            score_path(
                simplified,
                obstacles,
                routed_segments,
                used_ports.get(source.id, []),
                used_ports.get(target.id, []),
                label=label,
                label_obstacles=label_boxes,
                check_label=True,
                canvas_size=canvas_size,
                source=source,
                target=target,
            )
        )
    if not paths:
        start = source_ports[0]
        end = target_ports[0]
        return RoutedPath([start, end], float("inf"), 1)
    return min(paths, key=lambda item: item.score)


def port_candidates(shape: Shape, other: Shape) -> list[Point]:
    sx, sy = center(shape)
    ox, oy = center(other)
    dx, dy = ox - sx, oy - sy
    horizontal_first = abs(dx) >= abs(dy)
    if horizontal_first:
        first = "E" if dx >= 0 else "W"
        second = "S" if dy >= 0 else "N"
        third = "N" if second == "S" else "S"
        order = [first, second, third, "W" if first == "E" else "E"]
    else:
        first = "S" if dy >= 0 else "N"
        second = "E" if dx >= 0 else "W"
        third = "W" if second == "E" else "E"
        order = [first, second, third, "N" if first == "S" else "S"]
    points: list[Point] = [perimeter_point(shape, (ox, oy))]
    for index, side in enumerate(order):
        candidates = side_points(shape, side)
        if index == 0:
            points.extend(candidates)
        elif index == 1:
            points.extend(candidates[:2])
        else:
            points.extend(candidates[:1])
    return dedupe_points(points)


def side_points(shape: Shape, side: str) -> list[Point]:
    ratios = (0.5, 0.25, 0.75, 0.38, 0.62)
    if shape.kind == "ellipse":
        return ellipse_side_points(shape, side, ratios)
    if shape.kind == "diamond":
        return diamond_side_points(shape, side, ratios)
    if side == "E":
        return [(shape.x + shape.w, shape.y + shape.h * ratio) for ratio in ratios]
    if side == "W":
        return [(shape.x, shape.y + shape.h * ratio) for ratio in ratios]
    if side == "S":
        return [(shape.x + shape.w * ratio, shape.y + shape.h) for ratio in ratios]
    return [(shape.x + shape.w * ratio, shape.y) for ratio in ratios]


def perimeter_point(shape: Shape, toward: Point) -> Point:
    cx, cy = center(shape)
    dx = toward[0] - cx
    dy = toward[1] - cy
    if abs(dx) < 0.01 and abs(dy) < 0.01:
        return cx + shape.w / 2, cy
    if shape.kind == "ellipse":
        rx = max(1.0, shape.w / 2)
        ry = max(1.0, shape.h / 2)
        scale = 1 / math.sqrt((dx / rx) ** 2 + (dy / ry) ** 2)
        return cx + dx * scale, cy + dy * scale
    if shape.kind == "diamond":
        rx = max(1.0, shape.w / 2)
        ry = max(1.0, shape.h / 2)
        scale = 1 / (abs(dx) / rx + abs(dy) / ry)
        return cx + dx * scale, cy + dy * scale
    if abs(dx) * shape.h >= abs(dy) * shape.w:
        x = shape.x + shape.w if dx >= 0 else shape.x
        y = cy + dy * (shape.w / 2) / max(abs(dx), 1.0)
        return x, min(shape.y + shape.h, max(shape.y, y))
    y = shape.y + shape.h if dy >= 0 else shape.y
    x = cx + dx * (shape.h / 2) / max(abs(dy), 1.0)
    return min(shape.x + shape.w, max(shape.x, x)), y


def ellipse_side_points(shape: Shape, side: str, ratios: tuple[float, ...]) -> list[Point]:
    cx, cy = center(shape)
    rx = shape.w / 2
    ry = shape.h / 2
    points: list[Point] = []
    if side in {"E", "W"}:
        sign = 1 if side == "E" else -1
        for ratio in ratios:
            y = cy + (ratio - 0.5) * shape.h * 0.76
            x = cx + sign * rx * math.sqrt(max(0.0, 1 - ((y - cy) / ry) ** 2))
            points.append((x, y))
        return points
    sign = 1 if side == "S" else -1
    for ratio in ratios:
        x = cx + (ratio - 0.5) * shape.w * 0.76
        y = cy + sign * ry * math.sqrt(max(0.0, 1 - ((x - cx) / rx) ** 2))
        points.append((x, y))
    return points


def diamond_side_points(shape: Shape, side: str, ratios: tuple[float, ...]) -> list[Point]:
    cx, cy = center(shape)
    rx = shape.w / 2
    ry = shape.h / 2
    points: list[Point] = []
    if side in {"E", "W"}:
        sign = 1 if side == "E" else -1
        for ratio in ratios:
            y = cy + (ratio - 0.5) * shape.h * 0.72
            x = cx + sign * rx * (1 - abs(y - cy) / ry)
            points.append((x, y))
        return points
    sign = 1 if side == "S" else -1
    for ratio in ratios:
        x = cx + (ratio - 0.5) * shape.w * 0.72
        y = cy + sign * ry * (1 - abs(x - cx) / rx)
        points.append((x, y))
    return points


def candidate_paths(start: Point, end: Point, obstacles: list[Box], canvas_size: tuple[int, int]) -> list[list[Point]]:
    sx, sy = start
    tx, ty = end
    width, height = canvas_size
    margin = 48
    paths: list[list[Point]] = [
        [start, end],
        [start, (tx, sy), end],
        [start, (sx, ty), end],
    ]
    mid_x = (sx + tx) / 2
    mid_y = (sy + ty) / 2
    paths.extend(
        [
            [start, (mid_x, sy), (mid_x, ty), end],
            [start, (sx, mid_y), (tx, mid_y), end],
        ]
    )

    x_lanes = {mid_x, sx, tx, margin, width - margin}
    y_lanes = {mid_y, sy, ty, margin, height - margin}
    for left, top, right, bottom in obstacles:
        x_lanes.update({left - margin, right + margin})
        y_lanes.update({top - margin, bottom + margin})

    x_candidates = nearest_lanes(sx, tx, x_lanes, width)
    y_candidates = nearest_lanes(sy, ty, y_lanes, height)

    for lane_x in x_candidates:
        paths.append([start, (lane_x, sy), (lane_x, ty), end])
    for lane_y in y_candidates:
        paths.append([start, (sx, lane_y), (tx, lane_y), end])

    for lane_x in x_candidates[:5]:
        for lane_y in y_candidates[:5]:
            paths.append([start, (lane_x, sy), (lane_x, lane_y), (tx, lane_y), end])
            paths.append([start, (sx, lane_y), (lane_x, lane_y), (lane_x, ty), end])
    return paths


def grid_route(
    start: Point,
    end: Point,
    obstacles: list[Box],
    routed_segments: list[tuple[Point, Point]],
    canvas_size: tuple[int, int],
) -> list[Point] | None:
    """Find an orthogonal route through lanes placed around obstacle boxes."""
    sx, sy = start
    tx, ty = end
    width, height = canvas_size
    clearance = 34
    outer = 72
    x_lanes = {sx, tx, (sx + tx) / 2, outer, width - outer}
    y_lanes = {sy, ty, (sy + ty) / 2, outer, height - outer}
    for left, top, right, bottom in obstacles:
        x_lanes.update({left - clearance, left - 8, right + 8, right + clearance})
        y_lanes.update({top - clearance, top - 8, bottom + 8, bottom + clearance})
    x_lanes = select_lanes(x_lanes, sx, tx, width, outer)
    y_lanes = select_lanes(y_lanes, sy, ty, height, outer)

    nodes = {
        (x, y)
        for x in x_lanes
        for y in y_lanes
        if not any(point_inside_box((x, y), obstacle) for obstacle in obstacles)
    }
    nodes.add(start)
    nodes.add(end)
    if start not in nodes or end not in nodes:
        return None

    rows: dict[float, list[Point]] = {}
    cols: dict[float, list[Point]] = {}
    for point in nodes:
        rows.setdefault(point[1], []).append(point)
        cols.setdefault(point[0], []).append(point)
    for row in rows.values():
        row.sort(key=lambda point: point[0])
    for col in cols.values():
        col.sort(key=lambda point: point[1])

    neighbors: dict[Point, list[tuple[Point, str, float]]] = {point: [] for point in nodes}
    for row in rows.values():
        add_axis_neighbors(row, "h", neighbors, obstacles, routed_segments)
    for col in cols.values():
        add_axis_neighbors(col, "v", neighbors, obstacles, routed_segments)

    queue: list[tuple[float, int, Point, str]] = [(0, 0, start, "")]
    distances: dict[tuple[Point, str], float] = {(start, ""): 0}
    previous: dict[tuple[Point, str], tuple[Point, str]] = {}
    counter = 1
    best_state: tuple[Point, str] | None = None
    while queue:
        cost, _, point, axis = heapq.heappop(queue)
        state = (point, axis)
        if cost != distances.get(state):
            continue
        if point == end:
            best_state = state
            break
        for neighbor, next_axis, edge_cost in neighbors.get(point, []):
            turn_penalty = 0 if not axis or axis == next_axis else 70
            next_cost = cost + edge_cost + turn_penalty
            next_state = (neighbor, next_axis)
            if next_cost < distances.get(next_state, float("inf")):
                distances[next_state] = next_cost
                previous[next_state] = state
                heapq.heappush(queue, (next_cost, counter, neighbor, next_axis))
                counter += 1
    if best_state is None:
        return None

    path: list[Point] = []
    state = best_state
    while True:
        path.append(state[0])
        if state not in previous:
            break
        state = previous[state]
    path.reverse()
    return path


def select_lanes(values: set[float], start: float, end: float, limit: float, outer: float, max_count: int = 18) -> set[float]:
    required = {start, end, (start + end) / 2, outer, limit - outer}
    cleaned = {round(value, 2) for value in values if -outer <= value <= limit + outer}
    low, high = sorted((start, end))
    center_value = (start + end) / 2

    def score(value: float) -> tuple[float, float]:
        outside = 0 if low - 180 <= value <= high + 180 else min(abs(value - low), abs(value - high))
        return outside, abs(value - center_value)

    selected = set(required)
    for value in sorted(cleaned - selected, key=score)[: max(0, max_count - len(selected))]:
        selected.add(value)
    return {round(value, 2) for value in selected}


def add_axis_neighbors(
    ordered: list[Point],
    axis: str,
    neighbors: dict[Point, list[tuple[Point, str, float]]],
    obstacles: list[Box],
    routed_segments: list[tuple[Point, Point]],
) -> None:
    for first, second in zip(ordered, ordered[1:]):
        if not segment_clear(first, second, obstacles):
            continue
        crossing_penalty = 1800 * sum(1 for existing in routed_segments if real_segment_crossing((first, second), existing))
        cost = distance(first, second) + crossing_penalty
        neighbors[first].append((second, axis, cost))
        neighbors[second].append((first, axis, cost))


def segment_clear(a: Point, b: Point, obstacles: list[Box]) -> bool:
    return not any(segment_intersects_box(a, b, obstacle) for obstacle in obstacles)


def nearest_lanes(a: float, b: float, lanes: set[float], limit: float) -> list[float]:
    valid = [lane for lane in lanes if 24 <= lane <= limit - 24]
    center_value = (a + b) / 2
    outer_lanes = [lane for lane in valid if lane < 96 or lane > limit - 96]
    nearby = sorted(valid, key=lambda value: (abs(value - center_value), abs(value - a) + abs(value - b)))[:8]
    return sorted(set(outer_lanes + nearby), key=lambda value: (abs(value - center_value), abs(value - a) + abs(value - b)))[:10]


def score_path(
    points: list[Point],
    obstacles: list[Box],
    routed_segments: list[tuple[Point, Point]],
    source_ports: list[Point],
    target_ports: list[Point],
    *,
    label: str,
    label_obstacles: list[Box],
    check_label: bool,
    canvas_size: tuple[int, int],
    source: Shape,
    target: Shape,
) -> RoutedPath:
    segments = list(zip(points, points[1:]))
    blocked = sum(1 for segment in segments for obstacle in obstacles if segment_intersects_box(segment[0], segment[1], obstacle))
    crossings = sum(1 for segment in segments for existing in routed_segments if real_segment_crossing(segment, existing))
    bends = max(0, len(points) - 2)
    length = sum(distance(a, b) for a, b in segments)
    port_penalty = min_port_distance(points[0], source_ports) + min_port_distance(points[-1], target_ports)
    bounds_penalty = sum(point_bounds_penalty(point, canvas_size) for point in points)
    label_penalty = 0
    if label:
        longest = max((distance(a, b) for a, b in segments), default=0)
        if longest < 135:
            label_penalty += 1200 + (135 - longest) * 12
        if check_label:
            label_penalty += label_collision_penalty(label, points, label_obstacles, canvas_size)
    score = (
        blocked * 100000
        + crossings * 3200
        + bends * 90
        + length
        + port_penalty * 5
        + bounds_penalty * 80
        + sprawl_penalty(points) * 2.5
        + endpoint_alignment_penalty(points, source, target)
        + label_penalty
    )
    return RoutedPath(points, score, blocked)


def rescore_label_candidates(
    paths: list[RoutedPath],
    obstacles: list[Box],
    routed_segments: list[tuple[Point, Point]],
    source_ports: list[Point],
    target_ports: list[Point],
    label: str,
    label_obstacles: list[Box],
    canvas_size: tuple[int, int],
    source: Shape,
    target: Shape,
) -> list[RoutedPath]:
    if not label or not paths:
        return paths
    shortlist = sorted(paths, key=lambda item: item.score)[:18]
    return [
        score_path(
            item.points,
            obstacles,
            routed_segments,
            source_ports,
            target_ports,
            label=label,
            label_obstacles=label_obstacles,
            check_label=True,
            canvas_size=canvas_size,
            source=source,
            target=target,
        )
        for item in shortlist
    ]


def endpoint_alignment_penalty(points: list[Point], source: Shape, target: Shape) -> float:
    if len(points) < 2:
        return 10000
    penalty = endpoint_vector_penalty(center(source), points[0], points[1])
    penalty += endpoint_vector_penalty(center(target), points[-1], points[-2])
    return penalty


def endpoint_vector_penalty(shape_center: Point, endpoint: Point, adjacent: Point) -> float:
    outward = (endpoint[0] - shape_center[0], endpoint[1] - shape_center[1])
    segment = (adjacent[0] - endpoint[0], adjacent[1] - endpoint[1])
    out_len = math.hypot(outward[0], outward[1])
    seg_len = math.hypot(segment[0], segment[1])
    if out_len < 1 or seg_len < 1:
        return 4000
    cos = (outward[0] * segment[0] + outward[1] * segment[1]) / (out_len * seg_len)
    if cos <= 0:
        return 4500
    if cos < 0.18:
        return 1800
    if cos < 0.32:
        return 650
    return 0


def obstacle_margin(profile: str) -> float:
    if profile == "deployment":
        return 72
    if profile in {"c4", "use-case"}:
        return 64
    if profile == "class":
        return 54
    if profile == "ml-pipeline":
        return 34
    return 26


def label_obstacles(source: Shape, target: Shape, obstacles: list[Box]) -> list[Box]:
    return list(obstacles) + [expanded_shape_box(source, 8), expanded_shape_box(target, 8)]


def label_collision_penalty(label: str, points: list[Point], occupied: list[Box], canvas_size: tuple[int, int]) -> float:
    if not label or len(points) < 2:
        return 0
    label_w = min(135.0, max(54.0, len(label) * 7.2))
    label_h = 20.0 * max(1, math.ceil(label_w / 135.0))
    best = float("inf")
    for box in rough_label_boxes(points, label_w, label_h):
        penalty = 0.0
        if box[0] < 0 or box[1] < 0 or box[2] > canvas_size[0] or box[3] > canvas_size[1]:
            penalty += 10000
        penalty += 35000 * sum(1 for item in occupied if boxes_intersect(box, item))
        if any(segment_intersects_box(a, b, expanded_box(box, 2)) for a, b in zip(points, points[1:])):
            penalty += 2500
        center_x = (box[0] + box[2]) / 2
        center_y = (box[1] + box[3]) / 2
        nearest = min(distance_to_segment((center_x, center_y), a, b) for a, b in zip(points, points[1:]))
        penalty += nearest * 1.1
        best = min(best, penalty)
        if best == 0:
            break
    return best


def rough_label_boxes(points: list[Point], width: float, height: float) -> list[Box]:
    segments = sorted(
        zip(points, points[1:]),
        key=lambda pair: distance(pair[0], pair[1]),
        reverse=True,
    )
    boxes: list[Box] = []
    for a, b in segments[:4]:
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = max(1.0, math.hypot(dx, dy))
        nx, ny = -dy / length, dx / length
        for gap in (18, 30, 48, 74, 112, 170, 250):
            for direction in (-1, 1):
                cx = mx + nx * gap * direction
                cy = my + ny * gap * direction
                boxes.append((cx - width / 2 - 4, cy - height / 2 - 3, cx + width / 2 + 4, cy + height / 2 + 3))
    return boxes


def distance_to_segment(point: Point, a: Point, b: Point) -> float:
    px, py = point
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return distance(point, a)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    projection = (ax + t * dx, ay + t * dy)
    return distance(point, projection)


def sprawl_penalty(points: list[Point]) -> float:
    if len(points) < 2:
        return 0
    start = points[0]
    end = points[-1]
    direct = max(1.0, distance(start, end))
    min_x, max_x = sorted((start[0], end[0]))
    min_y, max_y = sorted((start[1], end[1]))
    slack = max(130.0, min(260.0, direct * 0.22))
    penalty = 0.0
    for x, y in points[1:-1]:
        if x < min_x - slack:
            penalty += min_x - slack - x
        elif x > max_x + slack:
            penalty += x - max_x - slack
        if y < min_y - slack:
            penalty += min_y - slack - y
        elif y > max_y + slack:
            penalty += y - max_y - slack
    return penalty


def min_port_distance(point: Point, used: list[Point]) -> float:
    if not used:
        return 0
    nearest = min(distance(point, item) for item in used)
    if nearest >= 34:
        return 0
    return 34 - nearest


def point_bounds_penalty(point: Point, canvas_size: tuple[int, int]) -> float:
    x, y = point
    width, height = canvas_size
    penalty = 0.0
    if x < 0:
        penalty += -x
    if y < 0:
        penalty += -y
    if x > width:
        penalty += x - width
    if y > height:
        penalty += y - height
    return penalty


def simplify_path(points: list[Point]) -> list[Point]:
    if not points:
        return []
    deduped = [points[0]]
    for point in points[1:]:
        if distance(point, deduped[-1]) >= 1:
            deduped.append(point)
    if len(deduped) <= 2:
        return deduped
    simplified = [deduped[0]]
    for index, point in enumerate(deduped[1:-1], start=1):
        prev = simplified[-1]
        nxt = deduped[index + 1]
        if is_collinear(prev, point, nxt):
            continue
        simplified.append(point)
    simplified.append(deduped[-1])
    return simplified


def is_collinear(a: Point, b: Point, c: Point) -> bool:
    return abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) < 0.01


def center(shape: Shape) -> Point:
    return shape.x + shape.w / 2, shape.y + shape.h / 2


def expanded_shape_box(shape: Shape, margin: float) -> Box:
    return shape.x - margin, shape.y - margin, shape.x + shape.w + margin, shape.y + shape.h + margin


def distance(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def dedupe_points(points: list[Point]) -> list[Point]:
    result: list[Point] = []
    for point in points:
        if not any(distance(point, existing) < 1 for existing in result):
            result.append(point)
    return result


def segment_intersects_box(a: Point, b: Point, box: Box) -> bool:
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


def point_inside_box(point: Point, box: Box) -> bool:
    x, y = point
    left, top, right, bottom = box
    return left < x < right and top < y < bottom


def real_segment_crossing(first: tuple[Point, Point], second: tuple[Point, Point]) -> bool:
    a, b = first
    c, d = second
    if shared_endpoint(a, b, c, d):
        return False
    return segments_intersect(a, b, c, d)


def shared_endpoint(a: Point, b: Point, c: Point, d: Point) -> bool:
    return any(distance(x, y) < 2 for x in (a, b) for y in (c, d))


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    def orient(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on_segment(p: Point, q: Point, r: Point) -> bool:
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


def expand_canvas_to_routes(canvas: Canvas, margin: float = 60) -> None:
    points = [
        point
        for connector in canvas.connectors
        for point in (connector.points or [])
    ]
    if not points:
        return
    min_x = min([shape.x for shape in canvas.shapes] + [point[0] for point in points])
    min_y = min([shape.y for shape in canvas.shapes] + [point[1] for point in points])
    shift_x = margin - min_x if min_x < margin else 0
    shift_y = margin - min_y if min_y < margin else 0
    if shift_x or shift_y:
        for shape in canvas.shapes:
            shape.x += shift_x
            shape.y += shift_y
        for connector in canvas.connectors:
            if connector.points:
                connector.points = [(x + shift_x, y + shift_y) for x, y in connector.points]
            if connector.label_position:
                lx, ly = connector.label_position
                connector.label_position = (lx + shift_x, ly + shift_y)
    max_x = max([shape.x + shape.w for shape in canvas.shapes] + [point[0] for point in points])
    max_y = max([shape.y + shape.h for shape in canvas.shapes] + [point[1] for point in points])
    canvas.width = max(canvas.width, int(max_x + margin + shift_x))
    canvas.height = max(canvas.height, int(max_y + margin + shift_y))
