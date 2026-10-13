import { Plugin } from "@opencode/plugin"
import { spawn } from "node:child_process"
import { existsSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"

const root =
  process.env.OPENCODE_MERMAID_DIR ||
  (import.meta as { dir?: string }).dir ||
  join(fileURLToPath(new URL(".", import.meta.url)))

const chromes = [
  "/usr/bin/google-chrome",
  "/usr/bin/google-chrome-stable",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
]

function findChrome() {
  return chromes.find((c) => existsSync(c))
}

function slug(title: string) {
  return (
    title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "diagram"
  )
}

function run(cmd: string, args: string[], signal?: AbortSignal) {
  return new Promise<{ code: number | null; err: string }>((resolve) => {
    const child = spawn(cmd, args, { stdio: ["ignore", "ignore", "pipe"] })
    let err = ""
    child.stderr?.on("data", (d) => (err += d.toString()))
    const timer = setTimeout(() => child.kill("SIGKILL"), 60_000)
    const abort = () => child.kill("SIGKILL")
    signal?.addEventListener("abort", abort, { once: true })
    child.on("error", (e) => resolve({ code: 1, err: String(e) }))
    child.on("close", (code) => {
      clearTimeout(timer)
      signal?.removeEventListener("abort", abort)
      resolve({ code, err })
    })
  })
}

function mermaidVersion() {
  // mermaid is a transitive dep of mermaid-cli: resolve it through mermaid-cli's
  // own node_modules so this works under both pnpm and npm layouts
  try {
    const cliDir = realpathSync(join(root, "node_modules", "@mermaid-js", "mermaid-cli"))
    const pkg = JSON.parse(readFileSync(join(cliDir, "..", "..", "mermaid", "package.json"), "utf8"))
    if (typeof pkg.version === "string") return pkg.version
  } catch {
    // version stays unknown if the layout is unexpected
  }
  return "unknown"
}

const MERMAID_VERSION = mermaidVersion()

function decodeEntities(text: string) {
  return text
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&")
}

// some diagram types (e.g. gitGraph) render parse errors as an "error diagram"
// with exit code 0, so mmdc's exit code alone cannot be trusted — inspect the svg
function parseErrorFromSvg(svg: string) {
  if (!svg.includes('aria-roledescription="error"')) return undefined
  const lines = [...svg.matchAll(/<text[^>]*class="error-text"[^>]*>([^<]*)<\/text>/g)]
    .map((m) => decodeEntities(m[1].trim()))
    .filter((line) => line.length > 0 && !line.startsWith("mermaid version"))
  return lines.length > 0 ? lines.join("\n") : "unknown parse error"
}

export default Plugin.define({
  id: "opencode-mermaid",
  async setup(ctx) {
    await ctx.tool.transform((editor) => {
      editor.add({
        name: "mermaid",
        description:
          `render a mermaid diagram and show it in a floating popup window on the user's screen. renders with mermaid ${MERMAID_VERSION}: only use syntax valid for that version, and prefer verifying unfamiliar syntax in smaller pieces first. the source is syntax-checked before anything is shown; on a syntax error nothing is displayed and the parse error is returned instead — fix the source and render again. use whenever the user asks for a diagram, flowchart, graph, timeline, or visual, and proactively whenever a diagram would clearly help explain the current topic, such as architecture, data flow, pipelines, state machines, git history, or sequences. the popup supports zoom, pan, drag, resize, and copying the mermaid source.`,
        input: {
          type: "object",
          properties: {
            source: { type: "string", description: "mermaid diagram source code" },
            title: { type: "string", description: "short title for the popup window" },
          },
          required: ["source"],
          additionalProperties: false,
        },
        execute: async (input: { source: string; title?: string }, context: { signal?: AbortSignal }) => {
          const title = input.title ?? "diagram"
          const dir = join(tmpdir(), "opencode-mermaid")
          mkdirSync(dir, { recursive: true })
          const base = `${slug(title)}-${Date.now().toString(36)}`
          const mmd = join(dir, `${base}.mmd`)
          const svg = join(dir, `${base}.svg`)
          const png = join(dir, `${base}.png`)
          const cfg = join(dir, `${base}-puppeteer.json`)
          writeFileSync(mmd, input.source)
          const chrome = findChrome()
          writeFileSync(cfg, JSON.stringify(chrome ? { executablePath: chrome } : {}))
          const mmdc = join(root, "node_modules", ".bin", "mmdc")
          const args = [
            "-p", cfg,
            "-c", join(root, "themes", "catppuccin.json"),
            "-i", mmd,
            "-b", "transparent",
            "-s", "3",
            "--quiet",
          ]

          const check = await run(mmdc, [...args, "-o", svg], context.signal)
          if (check.code !== 0 || !existsSync(svg)) {
            return { content: `mermaid ${MERMAID_VERSION} syntax check failed: ${check.err || `exit ${check.code}`}` }
          }
          const parseError = parseErrorFromSvg(readFileSync(svg, "utf8"))
          if (parseError) {
            return { content: `mermaid ${MERMAID_VERSION} syntax error — nothing was displayed. ${parseError}. fix the diagram source and render again` }
          }

          const result = await run(mmdc, [...args, "-o", png], context.signal)
          if (result.code !== 0 || !existsSync(png)) {
            return { content: `mermaid ${MERMAID_VERSION} render failed: ${result.err || `exit ${result.code}`}` }
          }
          const popup = spawn(
            "/usr/bin/python3",
            [join(root, "popup.py"), png, "--source", mmd, "--title", title],
            { detached: true, stdio: "ignore" },
          )
          popup.unref()
          return { content: `rendered and popped up: ${title} (mermaid ${MERMAID_VERSION})` }
        },
      })
    })
  },
})
