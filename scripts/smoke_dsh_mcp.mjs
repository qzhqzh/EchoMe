// Exercise an installed DSH bridge over real stdio, without an LLM or Hub call.
// Usage: node scripts/smoke_dsh_mcp.mjs <dsh-package-root> <echome-python>
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve, join } from "node:path";
import { pathToFileURL } from "node:url";

const [dshRoot, python] = process.argv.slice(2);
if (!dshRoot || !python) throw new Error("Usage: smoke_dsh_mcp.mjs <dsh-package-root> <echome-python>");
const requireDsh = createRequire(join(resolve(dshRoot), "package.json"));
const bridge = await import(pathToFileURL(requireDsh.resolve("@deepseek-ai/dsh-mcp-client")).href);
const metadata = JSON.parse(readFileSync(requireDsh.resolve("@deepseek-ai/dsh-mcp-client/package.json"), "utf8"));
const directory = mkdtempSync(join(tmpdir(), "echome-dsh-smoke-"));
try {
  for (const profile of ["core", "full"]) {
    const definitions = new Map();
    const cleanup = [];
    // Only the host registry/lifecycle is minimal. Discovery, naming, schema
    // adaptation, stdio transport and tool execution use the installed plugin.
    const ctx = {
      root: {}, get: () => undefined,
      logger: { info() {}, warn: console.error, error: console.error },
      effect(start) { cleanup.push(start()); },
      tools: {
        register(definition) {
          assert(!definitions.has(definition.name));
          definitions.set(definition.name, definition);
          return () => definitions.delete(definition.name);
        },
      },
    };
    try {
      await bridge.apply(ctx, {
        serverName: "echome", transport: "stdio", command: resolve(python),
        args: ["-m", "echome_mcp"], cwd: directory,
        env: { ECHOME_MCP_PROFILE: profile },
        toolCallTimeoutMs: 15000, failOnStartupError: true,
        reconnect: { enabled: false },
      });
      const capability = definitions.get("mcp__echome__echome_capabilities");
      assert(capability, "DSH did not register the capability tool");
      assert(definitions.has("mcp__echome__echome_context"));
      assert.equal(definitions.has("mcp__echome__echome_search_summary"), profile === "full");
      const args = { format: "json" };
      const result = await capability.execute(args, { signal: AbortSignal.timeout(15000) });
      assert(result.structuredContent, "structured result missing");
      const rendered = capability.output.render(args, result);
      const payload = JSON.parse(rendered.map((item) => item.text).join("\n"));
      assert.equal(payload.capabilities_version, result.structuredContent.capabilities_version);
      console.log(JSON.stringify({ dsh: metadata.version, profile, tools: definitions.size,
        capabilities: payload.capabilities_version, text_and_structured: "passed" }));
    } finally {
      for (const dispose of cleanup.reverse()) if (dispose) await dispose();
      assert.equal(definitions.size, 0, "DSH leaked tool registrations after shutdown");
    }
  }
} finally {
  rmSync(directory, { recursive: true, force: true });
}
