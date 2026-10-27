// Build the Satish browser extension from the same Nuxt app.
//
//   SATISH_API=https://satish.rogan.live SATISH_BOT=YourBot node apps/extension/build.mjs
//
// Output: apps/extension/dist (load unpacked in chrome://extensions) and
// apps/extension/satish-extension.zip (for the Chrome Web Store).
import { execSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const web = join(here, "..", "web");
const dist = join(here, "dist");
const api = (process.env.SATISH_API || "https://satish.rogan.live").replace(/\/$/, "");

const env = {
  ...process.env,
  SATISH_TARGET: "extension",
  NUXT_PUBLIC_API_BASE: api,
  NUXT_PUBLIC_API_PORT: "",
  NUXT_PUBLIC_BOT_USERNAME: process.env.SATISH_BOT || process.env.NUXT_PUBLIC_BOT_USERNAME || "",
};
console.log(`Building Satish extension for ${api} …`);
execSync("npx nuxi generate", { cwd: web, env, stdio: "inherit" });

rmSync(dist, { recursive: true, force: true });
cpSync(join(web, ".output", "public"), dist, { recursive: true });

// Extensions don't need pre-compressed copies or the SPA fallbacks.
const walk = (d) => readdirSync(d).flatMap((n) => (statSync(join(d, n)).isDirectory() ? walk(join(d, n)) : [join(d, n)]));
for (const f of walk(dist)) if (/\.(br|gz)$/.test(f) || /(^|\/)(200|404)\.html$/.test(relative(dist, f))) rmSync(f);

// MV3 forbids inline scripts: move each one into its own file.
let n = 0;
if (/type="importmap"/.test(readFileSync(join(dist, "index.html"), "utf8"))) {
  throw new Error("an import map slipped into the build; extension pages can't run it");
}
const html = readFileSync(join(dist, "index.html"), "utf8").replace(
  /<script(?![^>]*\bsrc=)(?![^>]*type="application\/json")([^>]*)>([\s\S]*?)<\/script>/g,
  (_m, attrs, body) => {
    if (!body.trim()) return "";
    const name = `inline-${n++}.js`;
    writeFileSync(join(dist, name), body);
    return `<script${attrs} src="/${name}"></script>`;
  },
);
writeFileSync(join(dist, "index.html"), html);

// Chrome rejects files or folders whose name starts with "_" (e.g. the
// "_id_" chunk from pages/pay/[id].vue): rename them and fix references.
const underscored = walk(dist).filter((f) => relative(dist, f).split("/").pop().startsWith("_"));
if (underscored.length) {
  const renames = underscored.map((f) => {
    const name = f.split("/").pop();
    const to = join(dirname(f), "u" + name);
    renameSync(f, to);
    return [name, "u" + name];
  });
  for (const f of walk(dist)) {
    if (!/\.(js|mjs|css|html|json)$/.test(f)) continue;
    let text = readFileSync(f, "utf8");
    let changed = false;
    for (const [from, to] of renames) {
      if (text.includes(from)) {
        text = text.split(from).join(to);
        changed = true;
      }
    }
    if (changed) writeFileSync(f, text);
  }
}
const reserved = walk(dist).map((f) => relative(dist, f)).filter((f) => f.split("/").some((part) => part.startsWith("_")));
if (reserved.length) throw new Error(`names starting with "_" aren't allowed in extensions: ${reserved.slice(0, 5).join(", ")}`);

const manifest = readFileSync(join(here, "manifest.template.json"), "utf8").replace("__API_ORIGIN__", new URL(api).origin);
writeFileSync(join(dist, "manifest.json"), manifest);
cpSync(join(here, "background.js"), join(dist, "background.js"));
mkdirSync(join(dist, "icons"), { recursive: true });
for (const size of [16, 32, 48, 128]) cpSync(join(here, "icons", `${size}.png`), join(dist, "icons", `${size}.png`));

const zip = join(here, "satish-extension.zip");
rmSync(zip, { force: true });
try {
  execSync(`cd "${dist}" && zip -qr "${zip}" .`);
} catch {
  console.warn("zip not found: load the dist folder unpacked instead");
}
const size = walk(dist).reduce((s, f) => s + statSync(f).size, 0);
console.log(`Done: ${relative(process.cwd(), dist)} (${(size / 1e6).toFixed(1)} MB, ${n} inline script(s) moved)${existsSync(zip) ? " + satish-extension.zip" : ""}`);
