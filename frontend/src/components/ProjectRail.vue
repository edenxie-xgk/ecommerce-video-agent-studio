<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NEmpty, NIcon, NInput, NSelect, NTag } from 'naive-ui'
import { ChevronRight, Plus } from '@lucide/vue'
import type { Project } from '../api/client'
import { platformOptions, projectStatusLabels } from '../constants/studio'

const props = defineProps<{
  projects: Project[]
  selectedProjectId: number | null
  loading: boolean
  title: string
  targetPlatform: string
}>()

const emit = defineEmits<{
  'update:title': [value: string]
  'update:targetPlatform': [value: string]
  create: []
  select: [projectId: number]
}>()

const titleModel = computed({
  get: () => props.title,
  set: (value: string) => emit('update:title', value),
})

const targetPlatformModel = computed({
  get: () => props.targetPlatform,
  set: (value: string) => emit('update:targetPlatform', value),
})
</script>

<template>
  <aside class="project-rail">
    <div class="rail-heading">
      <div>
        <span class="eyebrow">Projects</span>
        <h1>商品项目</h1>
      </div>
      <n-tag size="small" round>{{ projects.length }}</n-tag>
    </div>

    <div class="new-project">
      <n-input v-model:value="titleModel" placeholder="新项目名称" />
      <div class="new-project-row">
        <n-select v-model:value="targetPlatformModel" :options="platformOptions" />
        <n-button type="primary" aria-label="创建项目" @click="emit('create')">
          <template #icon><n-icon :component="Plus" /></template>
        </n-button>
      </div>
    </div>

    <div class="project-list" aria-label="项目列表">
      <button
        v-for="project in projects"
        :key="project.id"
        type="button"
        class="project-item"
        :class="{ active: project.id === selectedProjectId }"
        @click="emit('select', project.id)"
      >
        <span class="project-platform">
          {{ project.target_platform === 'douyin' ? '抖音' : '小红书' }}
        </span>
        <strong>{{ project.product_brief?.product_name || project.title }}</strong>
        <span>{{ projectStatusLabels[project.status] ?? project.status }}</span>
        <ChevronRight :size="16" />
      </button>
    </div>

    <n-empty v-if="!loading && !projects.length" description="先创建一个商品项目" />
  </aside>
</template>
