from __future__ import annotations

import json
from pathlib import Path
import re


def detect_profile(text: str, path: Path) -> str:
    stripped = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        return data["profile"]
    if re.search(r"^sequenceDiagram\b", stripped, re.M):
        return "sequence"
    if re.search(r"^classDiagram\b", stripped, re.M):
        return "class"
    if re.search(r"^erDiagram\b", stripped, re.M):
        return "erd"
    if re.search(r"^flowchart\b", stripped, re.M):
        if re.search(r"%%\s*profile:\s*ml[-_ ]pipeline", text, re.I):
            return "ml-pipeline"
        return "gost-flowchart"
    if "System_Boundary(" in text or "Container(" in text or "Person(" in text:
        return "c4"
    if re.search(r"\b(node|cloud|database|queue|artifact)\s+\"", text):
        return "deployment"
    if re.search(r"\busecase\s+\"", text) or re.search(r"\bactor\s+\"", text):
        return "use-case"
    raise ValueError(f"Cannot detect diagram profile for {path}")


def parse_source(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    profile = detect_profile(text, path)
    if path.suffix.lower() == ".json":
        return json.loads(text)
    if profile == "sequence":
        return parse_sequence_mermaid(text)
    if profile == "class":
        return parse_class_mermaid(text)
    if profile == "erd":
        return parse_erd_mermaid(text)
    if profile == "ml-pipeline":
        return parse_flowchart_mermaid(text, profile="ml-pipeline")
    if profile == "c4":
        return parse_c4_puml(text)
    if profile == "deployment":
        return parse_deployment_puml(text)
    if profile == "use-case":
        return parse_usecase_puml(text)
    raise ValueError(f"Parser for {profile} is not implemented")


def clean_label(value: str) -> str:
    value = value.strip().strip('"').strip("'")
    return re.sub(r"\s+", " ", value)


def parse_sequence_mermaid(text: str) -> dict:
    participants: dict[str, dict] = {}
    events: list[dict] = []
    stack: list[tuple[str, int]] = []

    def ensure(alias: str, label: str | None = None, kind: str = "participant") -> None:
        if alias not in participants:
            participants[alias] = {"id": alias, "label": label or alias, "kind": kind}

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("%%") or line == "sequenceDiagram":
            continue
        m = re.match(r"(actor|participant|database|queue|boundary|control|entity)\s+(\w+)(?:\s+as\s+(.+))?", line)
        if m:
            kind, alias, label = m.groups()
            ensure(alias, clean_label(label or alias), kind)
            continue
        m = re.match(r"(alt|loop|opt|par|critical|break)\s+(.+)", line)
        if m:
            kind, label = m.groups()
            stack.append((kind, len(events)))
            events.append({"type": "fragment_start", "kind": kind, "label": clean_label(label)})
            continue
        m = re.match(r"else\s*(.*)", line)
        if m:
            events.append({"type": "fragment_else", "label": clean_label(m.group(1) or "else")})
            continue
        if line == "end":
            events.append({"type": "fragment_end"})
            continue
        m = re.match(r"(\w+)\s*([-.=x]+>>?|-->>|->>|-\)|--\))\s*(\w+)\s*:\s*(.+)", line)
        if m:
            src, arrow, dst, label = m.groups()
            ensure(src)
            ensure(dst)
            events.append(
                {
                    "type": "message",
                    "source": src,
                    "target": dst,
                    "label": clean_label(label),
                    "return": "--" in arrow,
                    "async": ")" in arrow,
                }
            )
    return {"profile": "sequence", "title": "Request Processing Sequence", "participants": list(participants.values()), "events": events}


def parse_class_mermaid(text: str) -> dict:
    classes: dict[str, dict] = {}
    relationships: list[dict] = []
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("%%") or line == "classDiagram":
            continue
        if current:
            if line == "}":
                current = None
                continue
            if line.startswith("+") or line.startswith("-") or line.startswith("#") or line.startswith("~"):
                target = "methods" if "(" in line else "fields"
                classes[current].setdefault(target, []).append(line)
            continue
        m = re.match(r"class\s+(\w+)\s*(?:<<([^>]+)>>)?\s*\{?", line)
        if m:
            name, stereotype = m.groups()
            classes.setdefault(name, {"id": name, "label": name, "fields": [], "methods": []})
            if stereotype:
                classes[name]["stereotype"] = stereotype
            if line.endswith("{"):
                current = name
            continue
        m = re.match(r"(\w+)\s+([<|>*.o-]+)\s+(\w+)(?:\s*:\s*(.+))?", line)
        if m:
            left, rel, right, label = m.groups()
            for name in (left, right):
                classes.setdefault(name, {"id": name, "label": name, "fields": [], "methods": []})
            source, target = left, right
            kind = "association_no_arrow"
            if "<|--" in rel or "--|>" in rel:
                kind = "inheritance"
            elif "<|.." in rel or "..|>" in rel:
                kind = "implementation"
            elif "*--" in rel:
                kind = "composition"
            elif "o--" in rel:
                kind = "aggregation"
            elif "..>" in rel:
                kind = "dependency"
            elif "-->" in rel:
                kind = "directed_association"
            elif "<--" in rel:
                kind = "directed_association"
                source, target = right, left
            if rel.startswith("<|") or rel.startswith("..|"):
                source, target = right, left
            elif rel.endswith("*") or rel.endswith("o"):
                source, target = right, left
            relationships.append({"source": source, "target": target, "kind": kind, "label": clean_label(label or "")})
    return {"profile": "class", "title": "Diagram Toolkit Class Model", "classes": list(classes.values()), "relationships": relationships}


def parse_erd_mermaid(text: str) -> dict:
    entities: dict[str, dict] = {}
    relationships: list[dict] = []
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("%%") or line == "erDiagram":
            continue
        if current:
            if line == "}":
                current = None
                continue
            parts = line.split()
            if len(parts) >= 2:
                entities[current].setdefault("fields", []).append(" ".join(parts))
            continue
        m = re.match(r"(\w+)\s*\{", line)
        if m:
            current = m.group(1)
            entities.setdefault(current, {"id": current, "label": current, "fields": []})
            continue
        m = re.match(r"(\w+)\s+([}|o{|\|{|\|o|o\|{}.-]+)--([}|o{|\|{|\|o|o\|{}.-]+)\s+(\w+)\s*:\s*(.+)", line)
        if m:
            left, left_card, right_card, right, label = m.groups()
            for name in (left, right):
                entities.setdefault(name, {"id": name, "label": name, "fields": []})
            relationships.append(
                {
                    "source": left,
                    "target": right,
                    "label": clean_label(label),
                    "start": left_card,
                    "end": right_card,
                }
            )
    return {"profile": "erd", "title": "Project Data Model", "entities": list(entities.values()), "relationships": relationships}


def parse_flowchart_mermaid(text: str, profile: str) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("%%") or line.startswith("flowchart"):
            continue
        parts = re.split(r"\s*-->\s*", line)
        if len(parts) >= 2:
            left = parse_flow_node(parts[0])
            right_part = parts[1]
            label = ""
            m_label = re.match(r"\|([^|]+)\|\s*(.+)", right_part)
            if m_label:
                label, right_part = clean_label(m_label.group(1)), m_label.group(2)
            right = parse_flow_node(right_part)
            nodes[left["id"]] = nodes.get(left["id"], left)
            nodes[right["id"]] = nodes.get(right["id"], right)
            edges.append({"source": left["id"], "target": right["id"], "label": label})
            continue
        node = parse_flow_node(line)
        nodes[node["id"]] = nodes.get(node["id"], node)
    return {"profile": profile, "title": "ML Data Pipeline", "nodes": list(nodes.values()), "edges": edges}


def parse_flow_node(text: str) -> dict:
    text = text.strip().rstrip(";")
    patterns = [
        (r"^(\w+)\[\((.+)\)\]$", "database"),
        (r"^(\w+)\[\[(.+)\]\]$", "process"),
        (r"^(\w+)\(\((.+)\)\)$", "circle"),
        (r"^(\w+)\{(.+)\}$", "decision"),
        (r"^(\w+)\[(.+)\]$", "process"),
        (r"^(\w+)\((.+)\)$", "round"),
    ]
    for pattern, kind in patterns:
        m = re.match(pattern, text)
        if m:
            return {"id": m.group(1), "label": clean_label(m.group(2)), "kind": kind}
    return {"id": text, "label": text, "kind": "process"}


def parse_c4_puml(text: str) -> dict:
    elements: dict[str, dict] = {}
    relationships: list[dict] = []
    boundary: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("'") or line.startswith("@") or line.startswith("!"):
            continue
        m = re.match(r"System_Boundary\((\w+),\s*\"([^\"]+)\"\)\s*\{?", line)
        if m:
            boundary = {"id": m.group(1), "label": m.group(2)}
            continue
        m = re.match(r"(Person|System|System_Ext|Container|ContainerDb|Component)\((.+)\)", line)
        if m:
            kind, args = m.groups()
            values = split_args(args)
            if len(values) >= 2:
                element_id = values[0]
                elements[element_id] = {
                    "id": element_id,
                    "kind": kind,
                    "label": values[1],
                    "technology": values[2] if len(values) >= 3 else "",
                    "description": values[3] if len(values) >= 4 else "",
                    "inside_boundary": kind in {"Container", "ContainerDb", "Component"},
                }
            continue
        m = re.match(r"Rel\((.+)\)", line)
        if m:
            values = split_args(m.group(1))
            if len(values) >= 3:
                relationships.append(
                    {
                        "source": values[0],
                        "target": values[1],
                        "label": values[2],
                        "technology": values[3] if len(values) >= 4 else "",
                    }
                )
    return {"profile": "c4", "title": "C4 Container Diagram", "boundary": boundary, "elements": list(elements.values()), "relationships": relationships}


def split_args(args: str) -> list[str]:
    values: list[str] = []
    current = []
    in_string = False
    quote = ""
    for char in args:
        if char in {'"', "'"}:
            if not in_string:
                in_string, quote = True, char
                continue
            if quote == char:
                in_string = False
                continue
        if char == "," and not in_string:
            values.append(clean_label("".join(current)))
            current = []
        else:
            current.append(char)
    if current:
        values.append(clean_label("".join(current)))
    return values


def parse_deployment_puml(text: str) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    stack: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("'") or line.startswith("@"):
            continue
        if line == "}":
            if stack:
                stack.pop()
            continue
        m = re.match(r"(node|cloud|database|queue|artifact|component)\s+\"([^\"]+)\"\s+as\s+(\w+)\s*(\{)?", line)
        if m:
            kind, label, element_id, opens = m.groups()
            nodes[element_id] = {"id": element_id, "kind": kind, "label": label, "parent": stack[-1] if stack else None}
            if opens:
                stack.append(element_id)
            continue
        m = re.match(r"(\w+)\s+([-.]+>)\s+(\w+)\s*:\s*(.+)", line)
        if m:
            source, arrow, target, label = m.groups()
            edges.append({"source": source, "target": target, "label": clean_label(label), "dashed": "." in arrow, "kind": "dependency" if "." in arrow else "association"})
    return {"profile": "deployment", "title": "Production Deployment", "nodes": list(nodes.values()), "edges": edges}


def parse_usecase_puml(text: str) -> dict:
    actors: dict[str, dict] = {}
    usecases: dict[str, dict] = {}
    edges: list[dict] = []
    boundary = {"id": "system", "label": "System"}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("'") or line.startswith("@"):
            continue
        m = re.match(r"rectangle\s+\"([^\"]+)\"", line)
        if m:
            boundary["label"] = m.group(1)
            continue
        m = re.match(r"actor\s+\"([^\"]+)\"\s+as\s+(\w+)(?:\s+<<([^>]+)>>)?", line)
        if m:
            label, actor_id, side = m.groups()
            actors[actor_id] = {"id": actor_id, "label": label, "side": side or "left"}
            continue
        m = re.match(r"usecase\s+\"([^\"]+)\"\s+as\s+(\w+)", line)
        if m:
            label, usecase_id = m.groups()
            usecases[usecase_id] = {"id": usecase_id, "label": label}
            continue
        m = re.match(r"(\w+)\s+([-.]+>)\s+(\w+)(?:\s*:\s*(.+))?", line)
        if m:
            source, arrow, target, label = m.groups()
            edges.append({"source": source, "target": target, "label": clean_label(label or ""), "dashed": "." in arrow})
    return {"profile": "use-case", "title": "Use Case Diagram", "boundary": boundary, "actors": list(actors.values()), "usecases": list(usecases.values()), "edges": edges}
