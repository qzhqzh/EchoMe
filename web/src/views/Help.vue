<script setup lang="ts">
import { useI18n } from '@/i18n'

const { t } = useI18n()
</script>

<template>
  <div class="mx-auto max-w-4xl space-y-8 p-6">
    <!-- Header -->
    <div class="text-center">
      <h1 class="text-3xl font-bold text-slate-100">{{ t('help_title') }}</h1>
      <p class="mt-2 text-slate-400">
        {{ t('help_subtitle') }}
      </p>
    </div>

    <!-- Quick Start -->
    <section class="rounded-xl border border-slate-700 bg-slate-800 p-6">
      <h2 class="mb-4 text-xl font-semibold text-slate-100">{{ t('help_quick_start') }}</h2>
      <ol class="space-y-4 text-slate-300">
        <li class="flex gap-3">
          <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">1</span>
          <div>
            <p class="font-medium text-slate-100">{{ t('help_step1_title') }}</p>
            <code class="mt-1 block rounded bg-slate-900 px-3 py-1.5 text-sm text-emerald-400">pip install echome</code>
          </div>
        </li>
        <li class="flex gap-3">
          <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">2</span>
          <div>
            <p class="font-medium text-slate-100">{{ t('help_step2_title') }}</p>
            <code class="mt-1 block rounded bg-slate-900 px-3 py-1.5 text-sm text-emerald-400">echome init && echome login</code>
            <p class="mt-1 text-sm text-slate-400">{{ t('help_step2_desc') }}</p>
          </div>
        </li>
        <li class="flex gap-3">
          <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">3</span>
          <div>
            <p class="font-medium text-slate-100">{{ t('help_step3_title') }}</p>
            <code class="mt-1 block rounded bg-slate-900 px-3 py-1.5 text-sm text-emerald-400">echome add "Always use conventional commits"</code>
            <p class="mt-1 text-sm text-slate-400">{{ t('help_step3_desc') }}</p>
          </div>
        </li>
        <li class="flex gap-3">
          <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">4</span>
          <div>
            <p class="font-medium text-slate-100">{{ t('help_step4_title') }}</p>
            <code class="mt-1 block rounded bg-slate-900 px-3 py-1.5 text-sm text-emerald-400">echome sync</code>
            <p class="mt-1 text-sm text-slate-400">{{ t('help_step4_desc') }}</p>
          </div>
        </li>
      </ol>
    </section>

    <!-- Architecture Diagram -->
    <section class="rounded-xl border border-slate-700 bg-slate-800 p-6">
      <h2 class="mb-4 text-xl font-semibold text-slate-100">{{ t('help_architecture') }}</h2>
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
        {{ t('help_arch_note') }}
      </p>
    </section>

    <!-- Memory Flow -->
    <section class="rounded-xl border border-slate-700 bg-slate-800 p-6">
      <h2 class="mb-4 text-xl font-semibold text-slate-100">{{ t('help_memory_flow') }}</h2>
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
      <h2 class="mb-4 text-xl font-semibold text-slate-100">{{ t('help_memory_types') }}</h2>
      <p class="mb-4 text-sm text-slate-400">
        {{ t('help_memory_types_desc') }}
      </p>
      <div class="grid gap-3 sm:grid-cols-2">
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">🧠</span>
            <span class="font-semibold text-slate-100">identity</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">{{ t('help_type_identity') }}</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">🚫</span>
            <span class="font-semibold text-slate-100">guardrail</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">{{ t('help_type_guardrail') }}</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">💡</span>
            <span class="font-semibold text-slate-100">reasoning</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">{{ t('help_type_reasoning') }}</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">⚡</span>
            <span class="font-semibold text-slate-100">method</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">{{ t('help_type_method') }}</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">🔧</span>
            <span class="font-semibold text-slate-100">stack</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">{{ t('help_type_stack') }}</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">💬</span>
            <span class="font-semibold text-slate-100">style</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">{{ t('help_type_style') }}</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">📋</span>
            <span class="font-semibold text-slate-100">decision</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">{{ t('help_type_decision') }}</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">📚</span>
            <span class="font-semibold text-slate-100">context</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">{{ t('help_type_context') }}</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">📝</span>
            <span class="font-semibold text-slate-100">template</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">{{ t('help_type_template') }}</p>
        </div>
        <div class="rounded-lg border border-slate-600 bg-slate-900 p-3">
          <div class="flex items-center gap-2">
            <span class="text-lg">📁</span>
            <span class="font-semibold text-slate-100">project</span>
          </div>
          <p class="mt-1 text-sm text-slate-400">{{ t('help_type_project') }}</p>
        </div>
      </div>
    </section>

    <!-- Layers -->
    <section class="rounded-xl border border-slate-700 bg-slate-800 p-6">
      <h2 class="mb-4 text-xl font-semibold text-slate-100">{{ t('help_layers_title') }}</h2>
      <p class="mb-4 text-sm text-slate-400">
        {{ t('help_layers_desc') }}
      </p>
      <div class="space-y-3">
        <div class="flex items-start gap-3 rounded-lg border border-emerald-800 bg-emerald-950/30 p-3">
          <span class="rounded bg-emerald-700 px-2 py-0.5 text-xs font-bold text-white">L0</span>
          <div>
            <p class="font-medium text-slate-100">{{ t('help_l0_title') }}</p>
            <p class="text-sm text-slate-400">{{ t('help_l0_desc') }}</p>
          </div>
        </div>
        <div class="flex items-start gap-3 rounded-lg border border-blue-800 bg-blue-950/30 p-3">
          <span class="rounded bg-blue-700 px-2 py-0.5 text-xs font-bold text-white">L1</span>
          <div>
            <p class="font-medium text-slate-100">{{ t('help_l1_title') }}</p>
            <p class="text-sm text-slate-400">{{ t('help_l1_desc') }}</p>
          </div>
        </div>
        <div class="flex items-start gap-3 rounded-lg border border-slate-600 bg-slate-900/50 p-3">
          <span class="rounded bg-slate-600 px-2 py-0.5 text-xs font-bold text-white">L2</span>
          <div>
            <p class="font-medium text-slate-100">{{ t('help_l2_title') }}</p>
            <p class="text-sm text-slate-400">{{ t('help_l2_desc') }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- Key Commands -->
    <section class="rounded-xl border border-slate-700 bg-slate-800 p-6">
      <h2 class="mb-4 text-xl font-semibold text-slate-100">{{ t('help_cli_commands') }}</h2>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-slate-700 text-left">
              <th class="pb-2 pr-4 font-medium text-slate-300">{{ t('help_col_command') }}</th>
              <th class="pb-2 font-medium text-slate-300">{{ t('help_col_description') }}</th>
            </tr>
          </thead>
          <tbody class="text-slate-400">
            <tr class="border-b border-slate-800">
              <td class="py-2 pr-4"><code class="text-emerald-400">echome add</code></td>
              <td>{{ t('help_cmd_add') }}</td>
            </tr>
            <tr class="border-b border-slate-800">
              <td class="py-2 pr-4"><code class="text-emerald-400">echome list</code></td>
              <td>{{ t('help_cmd_list') }}</td>
            </tr>
            <tr class="border-b border-slate-800">
              <td class="py-2 pr-4"><code class="text-emerald-400">echome search &lt;query&gt;</code></td>
              <td>{{ t('help_cmd_search') }}</td>
            </tr>
            <tr class="border-b border-slate-800">
              <td class="py-2 pr-4"><code class="text-emerald-400">echome sync</code></td>
              <td>{{ t('help_cmd_sync') }}</td>
            </tr>
            <tr class="border-b border-slate-800">
              <td class="py-2 pr-4"><code class="text-emerald-400">echome review</code></td>
              <td>{{ t('help_cmd_review') }}</td>
            </tr>
            <tr class="border-b border-slate-800">
              <td class="py-2 pr-4"><code class="text-emerald-400">echome status</code></td>
              <td>{{ t('help_cmd_status') }}</td>
            </tr>
            <tr>
              <td class="py-2 pr-4"><code class="text-emerald-400">echome market browse</code></td>
              <td>{{ t('help_cmd_market') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Tips -->
    <section class="rounded-xl border border-slate-700 bg-slate-800 p-6">
      <h2 class="mb-4 text-xl font-semibold text-slate-100">{{ t('help_tips') }}</h2>
      <ul class="space-y-2 text-sm text-slate-300">
        <li class="flex gap-2">
          <span class="text-emerald-400">&#x2713;</span>
          {{ t('help_tip1') }}
        </li>
        <li class="flex gap-2">
          <span class="text-emerald-400">&#x2713;</span>
          {{ t('help_tip2') }}
        </li>
        <li class="flex gap-2">
          <span class="text-emerald-400">&#x2713;</span>
          {{ t('help_tip3') }}
        </li>
        <li class="flex gap-2">
          <span class="text-emerald-400">&#x2713;</span>
          {{ t('help_tip4') }}
        </li>
        <li class="flex gap-2">
          <span class="text-emerald-400">&#x2713;</span>
          {{ t('help_tip5') }}
        </li>
      </ul>
    </section>
  </div>
</template>
