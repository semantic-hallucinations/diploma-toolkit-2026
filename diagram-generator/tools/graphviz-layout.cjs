const fs = require("fs");
const { instance } = require("@viz-js/viz");

async function main() {
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  const viz = await instance();
  const result = viz.renderString(input.dot, { format: "json", engine: "dot" });
  process.stdout.write(result);
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
