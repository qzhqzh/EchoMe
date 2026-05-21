<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '@/api/client'
import { useToast } from '@/stores/toast'
import Modal from '@/components/Modal.vue'
import type { Project, ProjectCreate } from '@/types'

const { success } = useToast()

const projects = ref<Project[]>([])
const loading = ref(true)
const showForm = ref(false)
const editingProject = ref<Project | null>(null)
const saving = ref(false)
const showDeleteModal = ref(false)
const deleteTarget = ref<Project | null>(null)

// Form fields
const formId = ref('')
const formName = ref('')
const formDescription = ref('')
const formGitRemote = ref('')
const formPathPatterns = ref('')

onMounted(async () => {
  await loadProjects()
})

async function loadProjects(): Promise<void> {
  loading.value = true
  try {
    projects.value = await api.listProjects()
  } catch {
    // handled
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  editingProject.value = null
  formId.value = ''
  formName.value = ''
  formDescription.value = ''
  formGitRemote.value = ''
  formPathPatterns.value = ''
  showForm.value = true
}

function openEdit(project: Project): void {
  editingProject.value = project
  formId.value = project.id
  formName.value = project.name
  formDescription.value = project.description || ''
  formGitRemote.value = project.git_remote || ''
  formPathPatterns.value = project.path_patterns.join(', ')
  showForm.value = true
}

async function handleSubmit(): Promise<void> {
  if (!formId.value.trim() || !formName.value.trim()) return

  saving.value = true
  const data: ProjectCreate = {
    id: formId.value.trim(),
    name: formName.value.trim(),
    description: formDescription.value.trim() || null,
    git_remote: formGitRemote.value.trim() || null,
    path_patterns: formPathPatterns.value
      .split(',')
      .map(p => p.trim())
      .filter(Boolean),
  }

  try {
    if (editingProject.value) {
      await api.updateProject(editingProject.value.id, data)
      success('Project updated')
    } else {
      await api.createProject(data)
      success('Project created')
    }
    showForm.value = false
    await loadProjects()
  } catch {
    // handled
  } finally {
    saving.value = false
  }
}

function confirmDelete(project: Project): void {
  deleteTarget.value = project
  showDeleteModal.value = true
}

async function handleDelete(): Promise<void> {
  if (!deleteTarget.value) return
  try {
    await api.deleteProject(deleteTarget.value.id)
    success('Project deleted')
    showDeleteModal.value = false
    await loadProjects()
  } catch {
    // handled
  }
}
</script>

<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 class="text-2xl font-bold text-slate-100">Projects</h1>
        <p class="text-sm text-slate-400">Manage your project scopes</p>
      </div>
      <button class="btn-primary" @click="openCreate">
        <svg class="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
        </svg>
        Add Project
      </button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="grid gap-4 sm:grid-cols-2">
      <div v-for="i in 4" :key="i" class="card animate-pulse">
        <div class="h-5 w-1/2 rounded bg-slate-700" />
        <div class="mt-2 h-4 w-3/4 rounded bg-slate-700" />
      </div>
    </div>

    <!-- Empty state -->
    <div v-else-if="projects.length === 0" class="card py-12 text-center">
      <svg class="mx-auto h-12 w-12 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
      </svg>
      <p class="mt-3 text-slate-400">No projects yet</p>
      <button class="btn-primary mt-4" @click="openCreate">Add your first project</button>
    </div>

    <!-- Projects grid -->
    <div v-else class="grid gap-4 sm:grid-cols-2">
      <div
        v-for="project in projects"
        :key="project.id"
        class="card group"
      >
        <div class="flex items-start justify-between">
          <div class="min-w-0 flex-1">
            <h3 class="text-sm font-medium text-slate-100">{{ project.name }}</h3>
            <p class="mt-0.5 text-xs text-slate-500 font-mono">{{ project.id }}</p>
          </div>
          <div class="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              class="rounded p-1 text-slate-400 hover:bg-slate-700 hover:text-slate-200"
              @click="openEdit(project)"
            >
              <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
            </button>
            <button
              class="rounded p-1 text-slate-400 hover:bg-red-900/30 hover:text-red-400"
              @click="confirmDelete(project)"
            >
              <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
        </div>
        <p v-if="project.description" class="mt-2 text-xs text-slate-400 line-clamp-2">
          {{ project.description }}
        </p>
        <div class="mt-3 space-y-1">
          <p v-if="project.git_remote" class="text-xs text-slate-500 font-mono truncate">
            {{ project.git_remote }}
          </p>
          <div v-if="project.path_patterns.length > 0" class="flex flex-wrap gap-1">
            <span
              v-for="pattern in project.path_patterns"
              :key="pattern"
              class="inline-flex rounded bg-slate-700/50 px-1.5 py-0.5 text-xs text-slate-400 font-mono"
            >
              {{ pattern }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Create/Edit Form Modal -->
    <Modal
      :open="showForm"
      :title="editingProject ? 'Edit Project' : 'New Project'"
      @close="showForm = false"
    >
      <form class="space-y-4" @submit.prevent="handleSubmit">
        <div>
          <label class="mb-1.5 block text-sm font-medium text-slate-300">ID</label>
          <input
            v-model="formId"
            type="text"
            class="input-field"
            placeholder="owner/repo-name"
            :disabled="!!editingProject"
          />
        </div>
        <div>
          <label class="mb-1.5 block text-sm font-medium text-slate-300">Name</label>
          <input
            v-model="formName"
            type="text"
            class="input-field"
            placeholder="Project Name"
          />
        </div>
        <div>
          <label class="mb-1.5 block text-sm font-medium text-slate-300">Description</label>
          <textarea
            v-model="formDescription"
            class="input-field resize-none"
            rows="2"
            placeholder="Brief description..."
          />
        </div>
        <div>
          <label class="mb-1.5 block text-sm font-medium text-slate-300">Git Remote</label>
          <input
            v-model="formGitRemote"
            type="text"
            class="input-field"
            placeholder="git@github.com:owner/repo.git"
          />
        </div>
        <div>
          <label class="mb-1.5 block text-sm font-medium text-slate-300">Path Patterns</label>
          <input
            v-model="formPathPatterns"
            type="text"
            class="input-field"
            placeholder="~/projects/my-app, ~/work/app*"
          />
          <p class="mt-1 text-xs text-slate-500">Comma-separated local paths</p>
        </div>
      </form>
      <template #footer>
        <button class="btn-secondary" @click="showForm = false">Cancel</button>
        <button
          class="btn-primary"
          :disabled="!formId.trim() || !formName.trim() || saving"
          @click="handleSubmit"
        >
          {{ editingProject ? 'Update' : 'Create' }}
        </button>
      </template>
    </Modal>

    <!-- Delete confirmation -->
    <Modal :open="showDeleteModal" title="Delete Project" @close="showDeleteModal = false">
      <p class="text-sm text-slate-300">
        Are you sure you want to delete "{{ deleteTarget?.name }}"?
        This will not delete memories scoped to this project.
      </p>
      <template #footer>
        <button class="btn-secondary" @click="showDeleteModal = false">Cancel</button>
        <button class="btn-danger" @click="handleDelete">Delete</button>
      </template>
    </Modal>
  </div>
</template>
