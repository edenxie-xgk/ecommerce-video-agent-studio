import { defineStore } from 'pinia'
import {
  api,
  type CreateCreativeRunInput,
  type CreativeRun,
  type Project,
  type ProjectAsset,
  type StoryboardPromptBundle,
} from '../api/client'

type ProjectCollection<T> = Record<number, T[]>
type ProjectValue<T> = Record<number, T>

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

function assertProjectResponse(projectId: number, responseProjectId: number, resource: string) {
  if (responseProjectId !== projectId) {
    throw new Error(`${resource}返回了不匹配的项目数据。`)
  }
}

export const useStudioStore = defineStore('studio', {
  state: () => ({
    loading: false,
    bootstrapError: '',
    projects: [] as Project[],
    selectedProjectId: null as number | null,
    assetsByProjectId: {} as ProjectCollection<ProjectAsset>,
    creativeRunsByProjectId: {} as ProjectCollection<CreativeRun>,
    projectErrors: {} as ProjectValue<string>,
    projectLoadVersions: {} as ProjectValue<number>,
    pendingProjectLoads: {} as ProjectValue<number>,
    planningProjectId: null as number | null,
    promptReviewingRunId: null as number | null,
  }),
  getters: {
    selectedProject(state) {
      return state.projects.find((project) => project.id === state.selectedProjectId) ?? null
    },
    assets(state): ProjectAsset[] {
      const projectId = state.selectedProjectId
      return projectId === null ? [] : (state.assetsByProjectId[projectId] ?? [])
    },
    creativeRuns(state): CreativeRun[] {
      const projectId = state.selectedProjectId
      return projectId === null ? [] : (state.creativeRunsByProjectId[projectId] ?? [])
    },
    latestRun(state): CreativeRun | null {
      const projectId = state.selectedProjectId
      return projectId === null ? null : (state.creativeRunsByProjectId[projectId]?.[0] ?? null)
    },
    error(state): string {
      const projectId = state.selectedProjectId
      return (projectId === null ? '' : state.projectErrors[projectId]) || state.bootstrapError
    },
    projectLoading(state): boolean {
      const projectId = state.selectedProjectId
      return projectId !== null && state.pendingProjectLoads[projectId] !== undefined
    },
    planning(state): boolean {
      return state.planningProjectId !== null
    },
    operationBusy(state): boolean {
      return state.planningProjectId !== null || state.promptReviewingRunId !== null
    },
  },
  actions: {
    async bootstrap() {
      this.loading = true
      this.bootstrapError = ''
      try {
        this.projects = await api.listProjects()
        const projectId = this.projects[0]?.id ?? null
        this.selectedProjectId = projectId
        if (projectId !== null) await this.loadProject(projectId)
      } catch (error) {
        this.bootstrapError = errorMessage(error, '加载失败')
      } finally {
        this.loading = false
      }
    },
    async createProject(title: string, targetPlatform: string) {
      const project = await api.createProject({
        title,
        target_platform: targetPlatform,
      })
      this.projects.unshift(project)
      this.selectedProjectId = project.id
      this.assetsByProjectId[project.id] = []
      this.creativeRunsByProjectId[project.id] = []
      this.projectErrors[project.id] = ''
      return project
    },
    async loadProject(projectId: number) {
      this.selectedProjectId = projectId
      this.projectErrors[projectId] = ''

      const version = (this.projectLoadVersions[projectId] ?? 0) + 1
      this.projectLoadVersions[projectId] = version
      this.pendingProjectLoads[projectId] = version

      try {
        const [assets, creativeRuns] = await Promise.all([
          api.listAssets(projectId),
          api.listCreativeRuns(projectId),
        ])
        if (this.projectLoadVersions[projectId] !== version) return

        const invalidAsset = assets.find((asset) => asset.project_id !== projectId)
        const invalidRun = creativeRuns.find((run) => run.project_id !== projectId)
        if (invalidAsset || invalidRun) {
          throw new Error('项目接口返回了不匹配的数据。')
        }

        this.assetsByProjectId[projectId] = assets
        this.creativeRunsByProjectId[projectId] = creativeRuns
        this.bootstrapError = ''
      } catch (error) {
        if (this.projectLoadVersions[projectId] !== version) return
        this.projectErrors[projectId] = errorMessage(error, '项目加载失败')
        throw error
      } finally {
        if (this.pendingProjectLoads[projectId] === version) {
          delete this.pendingProjectLoads[projectId]
        }
      }
    },
    async generatePlan(input: CreateCreativeRunInput) {
      if (this.operationBusy) throw new Error('另一项操作正在进行，请稍后再试。')
      const projectId = input.projectId
      this.planningProjectId = projectId
      try {
        const run = await api.createCreativeRun(input)
        assertProjectResponse(projectId, run.project_id, '创意运行接口')
        this.upsertCreativeRun(projectId, run)
        await this.refreshProjectSnapshot(projectId)
        return run
      } catch (error) {
        await this.refreshProjectSnapshot(projectId)
        throw error
      } finally {
        if (this.planningProjectId === projectId) this.planningProjectId = null
      }
    },
    async reviewStoryboardPrompts(
      projectId: number,
      runId: number,
      expectedPromptRevision: number,
      storyboardPrompts: StoryboardPromptBundle,
    ) {
      if (this.operationBusy) throw new Error('另一项操作正在进行，请稍后再试。')
      this.promptReviewingRunId = runId
      try {
        const run = await api.reviewStoryboardPrompts({
          projectId,
          runId,
          expectedPromptRevision,
          storyboardPrompts,
        })
        assertProjectResponse(projectId, run.project_id, '分镜 Prompt 复检接口')
        if (run.id !== runId) throw new Error('分镜 Prompt 复检接口返回了不匹配的运行数据。')
        this.upsertCreativeRun(projectId, run)
        await this.refreshProjectSnapshot(projectId)
        return run
      } catch (error) {
        await this.refreshProjectSnapshot(projectId)
        throw error
      } finally {
        if (this.promptReviewingRunId === runId) this.promptReviewingRunId = null
      }
    },
    upsertCreativeRun(projectId: number, run: CreativeRun) {
      this.invalidateProjectLoad(projectId)
      const runs = this.creativeRunsByProjectId[projectId] ?? []
      this.creativeRunsByProjectId[projectId] = [
        run,
        ...runs.filter((item) => item.id !== run.id),
      ]
      const project = this.projects.find((item) => item.id === projectId)
      if (project) project.status = run.status
    },
    invalidateProjectLoad(projectId: number) {
      this.projectLoadVersions[projectId] = (this.projectLoadVersions[projectId] ?? 0) + 1
    },
    async refreshProjectSnapshot(projectId: number) {
      try {
        const [projects, assets, runs] = await Promise.all([
          api.listProjects(),
          api.listAssets(projectId),
          api.listCreativeRuns(projectId),
        ])
        if (!projects.some((project) => project.id === projectId)) return
        if (assets.some((asset) => asset.project_id !== projectId)) return
        if (runs.some((run) => run.project_id !== projectId)) return
        this.invalidateProjectLoad(projectId)
        this.projects = projects
        this.assetsByProjectId[projectId] = assets
        this.creativeRunsByProjectId[projectId] = runs
        this.bootstrapError = ''
      } catch {
        // 刷新失败不覆盖本次生成接口返回的真实错误，用户可以直接重新提交。
      }
    },
  },
})
