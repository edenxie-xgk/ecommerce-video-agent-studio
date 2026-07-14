<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useMessage, type UploadCustomRequestOptions } from 'naive-ui'
import type { ProductBrief } from '../api/client'
import AgentDecisionPanel from '../components/AgentDecisionPanel.vue'
import CreativeBriefPanel from '../components/CreativeBriefPanel.vue'
import ProjectRail from '../components/ProjectRail.vue'
import { useStudioStore } from '../stores/studio'

const store = useStudioStore()
const message = useMessage()

const DEFAULT_CAMPAIGN_GOAL = '让目标用户快速理解商品价值，并愿意进一步查看商品详情'
const projectTitle = ref('')
const projectTargetPlatform = ref('douyin')
const campaignGoals = reactive<Record<number, string>>({})
const briefForm = reactive<ProductBrief>({
  product_name: '',
  selling_points_text: '',
  target_audience_text: '',
  brand_tone: '',
  forbidden_words_text: '',
})

const selectedProject = computed(() => store.selectedProject)
const latestRun = computed(() => store.latestRun)
const campaignGoal = computed({
  get: () => {
    const projectId = store.selectedProjectId
    return projectId === null ? DEFAULT_CAMPAIGN_GOAL : (campaignGoals[projectId] ?? DEFAULT_CAMPAIGN_GOAL)
  },
  set: (value: string) => {
    const projectId = store.selectedProjectId
    if (projectId !== null) campaignGoals[projectId] = value
  },
})
const selectedProjectSaving = computed(
  () => store.savingProjectId !== null && store.savingProjectId === store.selectedProjectId,
)
const selectedProjectPlanning = computed(
  () => store.planningProjectId !== null && store.planningProjectId === store.selectedProjectId,
)
const selectedProjectUploading = computed(
  () => store.uploadingProjectId !== null && store.uploadingProjectId === store.selectedProjectId,
)
const workspaceBusy = computed(() => store.operationBusy || store.projectLoading)

watch(
  [selectedProject, latestRun],
  ([project, run]) => {
    const brief = project?.product_brief
    if (project) {
      const persistedGoal = run?.project_id === project.id ? run.campaign_goal?.trim() : ''
      const currentGoal = campaignGoals[project.id]
      if (persistedGoal && (currentGoal === undefined || currentGoal === DEFAULT_CAMPAIGN_GOAL)) {
        campaignGoals[project.id] = persistedGoal
      } else if (currentGoal === undefined) {
        campaignGoals[project.id] = DEFAULT_CAMPAIGN_GOAL
      }
    }
    briefForm.product_name = brief?.product_name === '未命名商品' ? '' : brief?.product_name ?? ''
    briefForm.selling_points_text = brief?.selling_points_text ?? ''
    briefForm.target_audience_text = brief?.target_audience_text ?? ''
    briefForm.brand_tone = brief?.brand_tone ?? ''
    briefForm.forbidden_words_text = brief?.forbidden_words_text ?? ''
  },
  { immediate: true },
)

onMounted(() => {
  store.bootstrap()
})

async function createProject() {
  if (store.operationBusy) return
  try {
    const project = await store.createProject(
      projectTitle.value.trim() || '新商品视频项目',
      projectTargetPlatform.value,
    )
    campaignGoals[project.id] = DEFAULT_CAMPAIGN_GOAL
    projectTitle.value = ''
    message.success('项目已创建，Agent 等待商品资料')
  } catch (error) {
    message.error(error instanceof Error ? error.message : '项目创建失败')
  }
}

async function selectProject(projectId: number) {
  try {
    await store.loadProject(projectId)
  } catch (error) {
    if (store.selectedProjectId === projectId) {
      message.error(error instanceof Error ? error.message : '项目加载失败')
    }
  }
}

async function saveBrief(notify = true) {
  const project = selectedProject.value
  if (!project || workspaceBusy.value) return
  const projectId = project.id
  const briefSnapshot = { ...briefForm }
  try {
    await store.saveBrief(projectId, briefSnapshot)
    if (notify) message.success(`${project.title}的商品事实已保存`)
  } catch (error) {
    message.error(error instanceof Error ? error.message : '商品事实保存失败')
  }
}

async function generatePlan() {
  const project = selectedProject.value
  if (!project || workspaceBusy.value) return
  const projectId = project.id
  const briefSnapshot = { ...briefForm }
  const campaignGoalSnapshot = campaignGoals[projectId] ?? DEFAULT_CAMPAIGN_GOAL
  try {
    const run = await store.generatePlan({
      projectId,
      campaignGoal: campaignGoalSnapshot,
    }, briefSnapshot)
    if (
      run.status === 'quality_blocked' ||
      run.action === 'resolve_quality_issues' ||
      run.result?.evaluation.passed === false
    ) {
      message.error(`${project.title}未通过质量门禁，请先处理阻断项`)
    } else {
      message.success(`${project.title}已完成创意决策和质量评估`)
    }
  } catch (error) {
    message.error(error instanceof Error ? error.message : '创意方案生成失败')
  }
}

async function uploadAsset(options: UploadCustomRequestOptions) {
  const project = selectedProject.value
  const file = options.file.file
  if (!project || !file || workspaceBusy.value) {
    options.onError()
    return
  }
  const projectId = project.id
  try {
    await store.uploadAsset(projectId, file)
    options.onFinish()
    message.success(`${project.title}的商品图已验证并保存`)
  } catch (error) {
    options.onError()
    message.error(error instanceof Error ? error.message : '图片上传失败')
  }
}
</script>

<template>
  <main class="studio-layout">
    <ProjectRail
      v-model:title="projectTitle"
      v-model:target-platform="projectTargetPlatform"
      :projects="store.projects"
      :selected-project-id="store.selectedProjectId"
      :loading="store.loading"
      @create="createProject"
      @select="selectProject"
    />
    <CreativeBriefPanel
      v-model:campaign-goal="campaignGoal"
      :project="selectedProject"
      :assets="store.assets"
      :brief="briefForm"
      :error="store.error"
      :saving="selectedProjectSaving"
      :planning="selectedProjectPlanning"
      :uploading="selectedProjectUploading"
      :busy="workspaceBusy"
      @save="saveBrief(true)"
      @generate="generatePlan"
      @upload="uploadAsset"
    />
    <AgentDecisionPanel
      :run="latestRun"
      :planning="selectedProjectPlanning"
      :busy="workspaceBusy"
    />
  </main>
</template>
