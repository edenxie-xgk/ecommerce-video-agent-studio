import { defineStore } from 'pinia'
import {
  api,
  type CreateCreativeRunInput,
  type CreativeRun,
  type ProductBrief,
  type Project,
  type ProjectAsset,
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
    savingProjectId: null as number | null,
    planningProjectId: null as number | null,
    uploadingProjectId: null as number | null,
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
    saving(state): boolean {
      return state.savingProjectId !== null
    },
    planning(state): boolean {
      return state.planningProjectId !== null
    },
    uploading(state): boolean {
      return state.uploadingProjectId !== null
    },
    operationBusy(state): boolean {
      return (
        state.savingProjectId !== null ||
        state.planningProjectId !== null ||
        state.uploadingProjectId !== null
      )
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
    async persistBrief(projectId: number, payload: ProductBrief) {
      const brief = await api.updateProductBrief(projectId, payload)
      assertProjectResponse(projectId, brief.project_id, '商品资料接口')
      const project = this.projects.find((item) => item.id === projectId)
      if (project) {
        project.product_brief = brief
        project.status = 'input_ready'
      }
      return brief
    },
    async saveBrief(projectId: number, payload: ProductBrief) {
      if (this.operationBusy) throw new Error('另一项操作正在进行，请稍后再试。')
      this.savingProjectId = projectId
      try {
        return await this.persistBrief(projectId, payload)
      } finally {
        if (this.savingProjectId === projectId) this.savingProjectId = null
      }
    },
    async uploadAsset(projectId: number, file: File) {
      if (this.operationBusy) throw new Error('另一项操作正在进行，请稍后再试。')
      this.uploadingProjectId = projectId
      try {
        const asset = await api.uploadAsset(projectId, file)
        assertProjectResponse(projectId, asset.project_id, '素材接口')
        this.invalidateProjectLoad(projectId)
        const current = this.assetsByProjectId[projectId] ?? []
        this.assetsByProjectId[projectId] = [
          asset,
          ...current.filter((item) => item.id !== asset.id),
        ]
        return asset
      } finally {
        if (this.uploadingProjectId === projectId) this.uploadingProjectId = null
      }
    },
    async generatePlan(input: CreateCreativeRunInput, briefPayload: ProductBrief) {
      if (this.operationBusy) throw new Error('另一项操作正在进行，请稍后再试。')
      const projectId = input.projectId
      this.planningProjectId = projectId
      this.savingProjectId = projectId
      try {
        await this.persistBrief(projectId, briefPayload)
        this.savingProjectId = null

        try {
          const run = await api.createCreativeRun(input)
          assertProjectResponse(projectId, run.project_id, '创意运行接口')
          this.upsertCreativeRun(projectId, run)
          return run
        } catch (error) {
          await this.refreshCreativeRunsAfterFailure(projectId)
          throw error
        }
      } finally {
        if (this.savingProjectId === projectId) this.savingProjectId = null
        if (this.planningProjectId === projectId) this.planningProjectId = null
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
    async refreshCreativeRunsAfterFailure(projectId: number) {
      try {
        const runs = await api.listCreativeRuns(projectId)
        if (runs.some((run) => run.project_id !== projectId)) return
        this.invalidateProjectLoad(projectId)
        this.creativeRunsByProjectId[projectId] = runs
      } catch {
        // Preserve the original generate error when recovery loading also fails.
      }
    },
  },
})
