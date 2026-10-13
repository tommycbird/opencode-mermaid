import { Plugin } from "@opencode/plugin"
import { spawn } from "node:child_process"
import { existsSync, mkdirSync, writeFileSync } from "node:fs"
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

export default Plugin.define({
  id: "opencode-mermaid",
  async setup(ctx) {
    await ctx.tool.transform((editor) => {
      editor.add({
        name: "mermaid",
        description:
          "render a mermaid diagram and show it in a floating popup window on the user's screen. use whenever the user asks for a diagram, flowchart, graph, timeline, or visual, and proactively whenever a diagram would clearly help explain the current topic, such as architecture, data flow, pipelines, state machines, git history, or sequences. the popup supports zoom, pan, drag, resize, and copying the mermaid source.",
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
          const png = join(dir, `${base}.png`)
          const cfg = join(dir, `${base}-puppeteer.json`)
          writeFileSync(mmd, input.source)
          const chrome = findChrome()
          writeFileSync(cfg, JSON.stringify(chrome ? { executablePath: chrome } : {}))
          const result = await run(
            join(root, "node_modules", ".bin", "mmdc"),
            [
              "-p", cfg,
              "-c", join(root, "themes", "catppuccin.json"),
              "-i", mmd,
              "-o", png,
              "-b", "transparent",
              "-s", "3",
              "--quiet",
            ],
            context.signal,
          )
          if (result.code !== 0 || !existsSync(png)) {
            return { content: `mermaid render failed: ${result.err || `exit ${result.code}`}` }
          }
          const popup = spawn(
            "/usr/bin/python3",
            [join(root, "popup.py"), png, "--source", mmd, "--title", title],
            { detached: true, stdio: "ignore" },
          )
          popup.unref()
          return { content: `rendered and popped up: ${title}` }
        },
      })
    })
  },
})
