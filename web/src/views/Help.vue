<script setup lang="ts">
// Static help page - no reactive data needed
</script>

<template>
  <div class="mx-auto max-w-4xl space-y-8 p-6">
    <!-- Header -->
    <div class="text-center">
      <h1 class="text-3xl font-bold text-slate-100">EchoMe Help</h1>
      <p class="mt-2 text-slate-400">
        Personal memory layer for AI CLI tools. Switch AI, not yourself.
      </p>
    </div>

    <!-- Quick Start -->
    <section class="rounded-xl border border-slate-700 bg-slate-800 p-6">
      <h2 class="mb-4 text-xl font-semibold text-slate-100">Quick Start</h2>
      <ol class="space-y-4 text-slate-300">
        <li class="flex gap-3">
          <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">1</span>
          <div>
            <p class="font-medium text-slate-100">Install CLI</p>
            <code class="mt-1 block rounded bg-slate-900 px-3 py-1.5 text-sm text-emerald-400">pip install echome-cli[mcp]</code>
          </div>
        </li>
        <li class="flex gap-3">
          <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">2</span>
          <div>
            <p class="font-medium text-slate-100">Initialize &amp; Login</p>
            <code class="mt-1 block rounded bg-slate-900 px-3 py-1.5 text-sm text-emerald-400">echome init && echome login</code>
            <p class="mt-1 text-sm text-slate-400">Creates vault at ~/.echome/, connects to Hub, registers MCP server</p>
          </div>
        </li>
        <li class="flex gap-3">
          <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">3</span>
          <div>
            <p class="font-medium text-slate-100">Add Your First Memory</p>
            <code class="mt-1 block rounded bg-slate-900 px-3 py-1.5 text-sm text-emerald-400">echome add "Always use conventional commits"</code>
            <p class="mt-1 text-sm text-slate-400">Or add via this Web UI: Memories &rarr; New Memory</p>
          </div>
        </li>
        <li class="flex gap-3">
          <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">4</span>
          <div>
            <p class="font-medium text-slate-100">Sync to AI CLI</p>
            <code class="mt-1 block rounded bg-slate-900 px-3 py-1.5 text-sm text-emerald-400">echome sync</code>
            <p class="mt-1 text-sm text-slate-400">Injects your memories into CLAUDE.md / AGENTS.md automatically</p>
          </div>
        </li>
      </ol>
    </section>

    <!-- Architecture Diagram -->
    <section class="rounded-xl border border-slate-700 bg-slate-800 p-6">
      <h2 class="mb-4 text-xl font-semibold text-slate-100">Architecture</h2>
      <div class="overflow-x-auto rounded-lg bg-slate-900 p-4">
        <pre class="text-sm leading-relaxed text-slate-300">
┌─────────────────────────────────────────────────────────────┐
│                        You (User)                           │
└────────────┬──────────────────┬─────────────────┬───────────┘
             │                  │                 │
             ▼                  ▼                 ▼
┌────────────────┐  ┌───────────────────┐  ┌──────────────┐
│   Web Console  │  │    CLI (echome)    │  │  AI CLI Tool │
│  (this app)    │  │  add/list/sync...  │  │ Claude / Codex│
└───────┬────────┘  └────────┬──────────┘  └──────┬───────┘
        │                    │                     │
        │                    │              ┌──────┴───────┐
        │                    │              │  MCP Server  │
        │                    │              │ (echome_mcp) │
        │                    │              └──────┬───────┘
        ▼                    ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    EchoMe Hub (API)                          │
│           FastAPI + PostgreSQL + pgvector                    │
└─────────────────────────────────────────────────────────────┘</pre>
      </div>
      <p class="mt-3 text-sm text-slate-400">
        All paths lead to the Hub. Memories stored once, available everywhere.
      </p>
    </section>

    <!-- Memory Flow -->
    <section class="rounded-xl border border-slate-700 bg-slate-800 p-6">
      <h2 class="mb-4 text-xl font-semibold text-slate-100">Memory Flow</h2>
      <div class="overflow-x-auto rounded-lg bg-slate-900 p-4">
        <pre class="text-sm leading-relaxed text-slate-300">
  Add Memory          Sync              AI Session
  ─────────          ────              ──────────
      │                │                    │
      ▼                ▼                    ▼
 ┌─────────┐    ┌───────────┐     ┌──────────────┐
 │ Hub DB  │───▶│  Render   │────▶│ CLAUDE.md /  │
 │ (store) │    │ (priority │     │ AGENTS.md    │
 └─────────┘    │  + tokens)│     └──────┬───────┘
                └───────────┘            │
                                         ▼
                                  ┌──────────────┐
                                  │ AI reads your│
                                  │ context on   │
                                  │ every session│
                                  └──────────────┘</pre>
      </div>
    </section>

    <!-- Memory Types -->
    <section class="rounded-xl border border-slate-700 bg-slate-800 p-6">
      <h2 class="mb-4 text-xl font-semibold text-slate-100">Memory Types</h2>
      <p class="mb-4 text-sm text-slate-400">
        Each memory has a <strong>type</strong> that determines its role and rendering priority.
      </p>
      <div class="grid gap-3 sm:grid-cols-2">
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">🧠</span>
            <span class="font-semibold text-slate-100">identity</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">Who you are, communication style, persona</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">🚫</span>
            <span class="font-semibold text-slate-100">guardrail</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">Red lines, things AI must never do</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">💡</span>
            <span class="font-semibold text-slate-100">reasoning</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">Thinking frameworks, decision processes</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">⚡</span>
            <span class="font-semibold text-slate-100">method</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">Workflow rules, conventions, processes</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">🔧</span>
            <span class="font-semibold text-slate-100">stack</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">Tech preferences, frameworks, tools</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">💬</span>
            <span class="font-semibold text-slate-100">style</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">Code style, formatting, naming conventions</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">📋</span>
            <span class="font-semibold text-slate-100">decision</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">Architecture choices, past decisions</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">📚</span>
            <span class="font-semibold text-slate-100">context</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">Domain knowledge, background info</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">📝</span>
            <span class="font-semibold text-slate-100">template</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">Code snippets, boilerplate templates</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">📁</span>
            <span class="font-semibold text-slate-100">project</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">Project-specific context and details</p>
        </div>
      </div>
    </section>

    <!-- Layers -->
    <section class="rounded-xl border border-slate-700 bg-slate-800 p-6">
      <h2 class="mb-4 text-xl font-semibold text-slate-100">Memory Layers (L0 / L1 / L2)</h2>
      <p class="mb-4 text-sm text-slate-400">
        Layers control <strong>when</strong> a memory is loaded into AI context.
      </p>
      <div class="space-y-3">
        <div class="flex items-start gap-3 rounded-lg border border-emerald-800 bg-emerald-950/30 p-3">
          <span class="rounded bg-emerald-700 px-2 py-0.5 text-xs font-bold text-white">L0</span>
          <div>
            <p class="font-medium text-slate-100">Always Loaded</p>
            <p class="text-sm text-slate-400">Core identity, critical guardrails. Injected into CLAUDE.md on every sync. Limited to ~1500 tokens.</p>
          </div>
        </div>
        <div class="flex items-start gap-3 rounded-lg border border-blue-800 bg-blue-950/30 p-3">
          <span class="rounded bg-blue-700 px-2 py-0.5 text-xs font-bold text-white">L1</span>
          <div>
            <p class="font-medium text-slate-100">Project-Level</p>
            <p class="text-sm text-slate-400">Loaded when working in a matched project. Tech stack, project conventions. ~2000 tokens.</p>
          </div>
        </div>
        <div class="flex items-start gap-3 rounded-lg border border-slate-600 bg-slate-900/50 p-3">
          <span class="rounded bg-slate-600 px-2 py-0.5 text-xs font-bold text-white">L2</span>
          <div>
            <p class="font-medium text-slate-100">On-Demand (MCP)</p>
            <p class="text-sm text-slate-400">Retrieved via MCP search when AI needs specific context. No token limit. Most memories live here.</p>
          </div>
        </div>
      </div>
    </section>

    <!-- Key Commands -->
    <section class="rounded-xl border border-slate-700 bg-slate-800 p-6">
      <h2 class="mb-4 text-xl font-semibold text-slate-100">CLI Commands</h2>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-slate-700 text-left">
              <th class="pb-2 pr-4 font-medium text-slate-300">Command</th>
              <th class="pb-2 font-medium text-slate-300">Description</th>
            </tr>
          </thead>
          <tbody class="text-slate-400">
            <tr class="border-b border-slate-800">
              <td class="py-2 pr-4"><code class="text-emerald-400">echome add</code></td>
              <td>Add a new memory (interactive or with flags)</td>
            </tr>
            <tr class="border-b border-slate-800">
              <td class="py-2 pr-4"><code class="text-emerald-400">echome list</code></td>
              <td>List all memories with filters</td>
            </tr>
            <tr class="border-b border-slate-800">
              <td class="py-2 pr-4"><code class="text-emerald-400">echome search &lt;query&gt;</code></td>
              <td>Semantic + keyword search</td>
            </tr>
            <tr class="border-b border-slate-800">
              <td class="py-2 pr-4"><code class="text-emerald-400">echome sync</code></td>
              <td>Render &amp; inject memories into AI CLI config</td>
            </tr>
            <tr class="border-b border-slate-800">
              <td class="py-2 pr-4"><code class="text-emerald-400">echome review</code></td>
              <td>Approve/reject AI-suggested memories</td>
            </tr>
            <tr class="border-b border-slate-800">
              <td class="py-2 pr-4"><code class="text-emerald-400">echome status</code></td>
              <td>Check Hub connection, injection status</td>
            </tr>
            <tr>
              <td class="py-2 pr-4"><code class="text-emerald-400">echome market browse</code></td>
              <td>Browse &amp; fork public memories</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Tips -->
    <section class="rounded-xl border border-slate-700 bg-slate-800 p-6">
      <h2 class="mb-4 text-xl font-semibold text-slate-100">Tips</h2>
      <ul class="space-y-2 text-sm text-slate-300">
        <li class="flex gap-2">
          <span class="text-emerald-400">&#x2713;</span>
          Say "remember this" to AI &mdash; it will save via MCP (pending your review)
        </li>
        <li class="flex gap-2">
          <span class="text-emerald-400">&#x2713;</span>
          Use <strong>guardrail</strong> type for things AI must never violate
        </li>
        <li class="flex gap-2">
          <span class="text-emerald-400">&#x2713;</span>
          Keep L0 memories short &mdash; they count against token budget every session
        </li>
        <li class="flex gap-2">
          <span class="text-emerald-400">&#x2713;</span>
          Run <code class="text-emerald-400">echome sync</code> after adding new L0/L1 memories
        </li>
        <li class="flex gap-2">
          <span class="text-emerald-400">&#x2713;</span>
          Use the Market to discover useful community memories
        </li>
      </ul>
    </section>
  </div>
</template>
