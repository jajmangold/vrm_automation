#!/usr/bin/env node
const fs = require("fs");
const Module = require("module");
const modulePaths = [];

for (const candidate of [
  process.env.GLTF_TRANSFORM_NODE_PATH,
  "/usr/local/lib/node_modules/@gltf-transform/cli/node_modules",
]) {
  addModulePath(candidate);
}

function addModulePath(candidate) {
  if (!candidate || !fs.existsSync(candidate)) {
    return;
  }
  if (!modulePaths.includes(candidate)) {
    modulePaths.push(candidate);
  }
  if (!Module.globalPaths.includes(candidate)) {
    Module.globalPaths.push(candidate);
  }
}

const npxRoot = `${process.env.HOME || ""}/.npm/_npx`;
if (fs.existsSync(npxRoot)) {
  for (const entry of fs.readdirSync(npxRoot)) {
    addModulePath(`${npxRoot}/${entry}/node_modules`);
  }
}

function requireFromKnownPaths(name) {
  try {
    return require(name);
  } catch (error) {
    for (const basePath of modulePaths) {
      try {
        return Module.createRequire(`${basePath}/`)(name);
      } catch (_innerError) {
        // Try the next known npm/npx module root.
      }
    }
    throw error;
  }
}

const { NodeIO } = requireFromKnownPaths("@gltf-transform/core");
const { ALL_EXTENSIONS } = requireFromKnownPaths("@gltf-transform/extensions");

async function main() {
  const input = process.argv[2];
  const output = process.argv[3];
  if (!input || !output) {
    throw new Error("usage: densify_gltf_sparse_accessors.cjs <input.glb> <output.glb>");
  }

  const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
  const document = await io.read(input);
  let sparseAccessors = 0;
  for (const accessor of document.getRoot().listAccessors()) {
    if (accessor.getSparse()) {
      accessor.setSparse(false);
      sparseAccessors += 1;
    }
  }
  await io.write(output, document);
  console.log(JSON.stringify({ status: "ok", sparse_accessors_densified: sparseAccessors, output }));
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
