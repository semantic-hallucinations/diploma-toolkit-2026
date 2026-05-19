const fs = require("fs");
const ELK = require("elkjs/lib/elk.bundled.js");

async function main() {
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  const elk = new ELK();
  let graph;
  if (input.graph) {
    graph = input.graph;
    graph.layoutOptions = {
      "elk.algorithm": "layered",
      "elk.direction": input.direction || "RIGHT",
      "elk.hierarchyHandling": input.hierarchyHandling || "INCLUDE_CHILDREN",
      "elk.spacing.nodeNode": String(input.nodeSpacing || 110),
      "elk.layered.spacing.nodeNodeBetweenLayers": String(input.layerSpacing || 150),
      "elk.edgeRouting": input.edgeRouting || "ORTHOGONAL",
      "elk.spacing.edgeNode": String(input.edgeSpacing || 42),
      "elk.spacing.edgeEdge": String(Math.max(18, Math.round((input.edgeSpacing || 42) * 0.65))),
      "elk.layered.spacing.edgeNodeBetweenLayers": String(input.edgeSpacing || 42),
      "elk.layered.spacing.edgeEdgeBetweenLayers": String(Math.max(18, Math.round((input.edgeSpacing || 42) * 0.65))),
      "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
      "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
      ...(graph.layoutOptions || {}),
    };
  } else {
    graph = {
      id: "root",
      layoutOptions: {
        "elk.algorithm": "layered",
        "elk.direction": input.direction || "RIGHT",
        "elk.spacing.nodeNode": String(input.nodeSpacing || 110),
        "elk.layered.spacing.nodeNodeBetweenLayers": String(input.layerSpacing || 150),
        "elk.edgeRouting": input.edgeRouting || "ORTHOGONAL",
        "elk.spacing.edgeNode": String(input.edgeSpacing || 42),
        "elk.spacing.edgeEdge": String(Math.max(18, Math.round((input.edgeSpacing || 42) * 0.65))),
        "elk.layered.spacing.edgeNodeBetweenLayers": String(input.edgeSpacing || 42),
        "elk.layered.spacing.edgeEdgeBetweenLayers": String(Math.max(18, Math.round((input.edgeSpacing || 42) * 0.65))),
        "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
        "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
      },
      children: input.nodes.map((node) => ({
        id: node.id,
        width: node.width,
        height: node.height,
      })),
      edges: input.edges.map((edge) => ({
        id: edge.id,
        sources: [edge.source],
        targets: [edge.target],
      })),
    };
  }
  const result = await elk.layout(graph);
  process.stdout.write(JSON.stringify(result));
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
