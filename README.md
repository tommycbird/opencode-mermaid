# opencode-mermaid

opencode v2 plugin that renders mermaid diagrams into a translucent gtk popup window. zoom, pan, drag, resize, copy source.

## dependencies

- node 20+, pnpm
- python3 with pygobject (gtk3)
- chrome or chromium

## install

```sh
git clone https://github.com/tommycbird/opencode-mermaid ~/repos/opencode-mermaid
cd ~/repos/opencode-mermaid
PUPPETEER_SKIP_DOWNLOAD=1 pnpm install
```

add to ~/.config/opencode/opencode.jsonc:

```json
"plugins": ["/home/YOU/repos/opencode-mermaid"]
```

restart opencode.
