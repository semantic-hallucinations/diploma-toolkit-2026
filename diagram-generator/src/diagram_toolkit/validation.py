from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from .rendering import (
    Canvas,
    Connector,
    FONT_SMALL,
    boxes_intersect,
    choose_label_position,
    connector_points,
    expanded_box,
    label_obstacle_boxes,
    label_box_at,
    wrap_text,
)
from .routing import NON_OBSTACLE_KINDS, real_segment_crossing, segment_intersects_box


Point = tuple[float, float]
Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    kind: str
    message: str
    connector_id: str = ""
    shape_id: str = ""

    def format(self) -> str:
        location = []
        if self.connector_id:
            location.append(f"connector={self.connector_id}")
        if self.shape_id:
            location.append(f"shape={self.shape_id}")
        suffix = f" ({', '.join(location)})" if location else ""
        return f"{self.severity.upper()} {self.kind}: {self.message}{suffix}"


def validate_canvas(canvas: Canvas) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    shape_map = canvas.shape_map()
    visible_shapes = [shape for shape in canvas.shapes if shape.kind not in NON_OBSTACLE_KINDS]
    shape_boxes = {
        shape.id: expanded_box((shape.x, shape.y, shape.x + shape.w, shape.y + shape.h), 4)
        for shape in visible_shapes
    }

    diagnostics.extend(validate_shape_bounds(canvas, shape_boxes))
    diagnostics.extend(validate_shape_overlaps(shape_boxes))
    diagnostics.extend(validate_connectors(canvas, shape_boxes))
    label_boxes = dict(shape_boxes)
    for shape in canvas.shapes:
        for index, box in enumerate(label_obstacle_boxes(shape)):
            label_boxes[f"{shape.id}:label:{index}"] = expanded_box(box, 4)
    diagnostics.extend(validate_labels(canvas, label_boxes))

    missing = [
        connector
        for connector in canvas.connectors
        if connector.source not in shape_map or connector.target not in shape_map
    ]
    for connector in missing:
        diagnostics.append(
            Diagnostic(
                "error",
                "missing-endpoint",
                "connector references a shape that is not present in the canvas",
                connector.id,
            )
        )
    return diagnostics


def validate_shape_bounds(canvas: Canvas, shape_boxes: dict[str, Box]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for shape_id, box in shape_boxes.items():
        left, top, right, bottom = box
        if left < 0 or top < 0 or right > canvas.width or bottom > canvas.height:
            diagnostics.append(
                Diagnostic("error", "shape-out-of-bounds", "shape is outside the canvas bounds", shape_id=shape_id)
            )
    return diagnostics


def validate_shape_overlaps(shape_boxes: dict[str, Box]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for first_id, second_id in combinations(shape_boxes, 2):
        if boxes_intersect(shape_boxes[first_id], shape_boxes[second_id]):
            diagnostics.append(
                Diagnostic(
                    "error",
                    "shape-overlap",
                    f"shape overlaps another shape: {second_id}",
                    shape_id=first_id,
                )
            )
    return diagnostics


def validate_connectors(canvas: Canvas, shape_boxes: dict[str, Box]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    shape_map = canvas.shape_map()
    connector_segments: list[tuple[Connector, Point, Point]] = []
    for connector in canvas.connectors:
        points = connector_points(connector, shape_map)
        if len(points) < 2:
            diagnostics.append(Diagnostic("error", "empty-route", "connector has no drawable route", connector.id))
            continue
        for start, end in zip(points, points[1:]):
            connector_segments.append((connector, start, end))
            for shape_id, box in shape_boxes.items():
                if shape_id in {connector.source, connector.target}:
                    continue
                if segment_intersects_box(start, end, box):
                    diagnostics.append(
                        Diagnostic(
                            "error",
                            "segment-shape",
                            "connector segment intersects an unrelated shape",
                            connector.id,
                            shape_id,
                        )
                    )
        if connector.label and connector.source != connector.target and longest_segment_length(points) < 80:
            diagnostics.append(
                Diagnostic(
                    "warning",
                    "short-labeled-segment",
                    "labelled connector has no comfortably long segment for its label",
                    connector.id,
                )
            )
    for first, second in combinations(connector_segments, 2):
        first_connector, first_start, first_end = first
        second_connector, second_start, second_end = second
        if first_connector.id == second_connector.id:
            continue
        if {first_connector.source, first_connector.target} & {second_connector.source, second_connector.target}:
            continue
        if real_segment_crossing((first_start, first_end), (second_start, second_end)):
            diagnostics.append(
                Diagnostic(
                    "warning",
                    "line-crossing",
                    f"connector crosses {second_connector.id}",
                    first_connector.id,
                )
            )
    return diagnostics


def validate_labels(canvas: Canvas, shape_boxes: dict[str, Box]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    shape_map = canvas.shape_map()
    occupied = list(shape_boxes.values())
    for connector in canvas.connectors:
        if not connector.label:
            continue
        points = connector_points(connector, shape_map)
        if not points:
            continue
        label = wrap_text(connector.label.replace("\\n", "\n"), 135, FONT_SMALL)
        lx, ly = choose_label_position(label, points, connector.label_position, occupied, (canvas.width, canvas.height), FONT_SMALL)
        box = label_box_at(label, lx, ly, FONT_SMALL)
        if box[0] < 0 or box[1] < 0 or box[2] > canvas.width or box[3] > canvas.height:
            diagnostics.append(Diagnostic("error", "label-out-of-bounds", "connector label is outside canvas", connector.id))
        for occupied_box in occupied:
            if boxes_intersect(box, occupied_box):
                diagnostics.append(
                    Diagnostic("error", "label-overlap", "connector label overlaps a shape or another label", connector.id)
                )
                break
        for start, end in zip(points, points[1:]):
            if segment_intersects_box(start, end, expanded_box(box, 2)):
                diagnostics.append(Diagnostic("warning", "label-line-overlap", "connector label touches its route", connector.id))
                break
        occupied.append(expanded_box(box, 5))
    return diagnostics


def longest_segment_length(points: list[Point]) -> float:
    if len(points) < 2:
        return 0
    return max(((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5 for start, end in zip(points, points[1:]))


def summarize_diagnostics(diagnostics: list[Diagnostic]) -> str:
    if not diagnostics:
        return "OK"
    return "\n".join(diagnostic.format() for diagnostic in diagnostics)


def has_errors(diagnostics: list[Diagnostic]) -> bool:
    return any(diagnostic.severity == "error" for diagnostic in diagnostics)
