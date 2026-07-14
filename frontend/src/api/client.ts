const API_BASE = import.meta.env.VITE_API_BASE ?? '/api/v1'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (!(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!response.ok) {
    const text = await response.text()
    try {
      const parsed = JSON.parse(text) as { detail?: unknown }
      throw new Error(formatApiError(parsed.detail, text, response.status))
    } catch (error) {
      if (error instanceof SyntaxError) throw new Error(text || `Request failed: ${response.status}`)
      throw error
    }
  }
  return response.json() as Promise<T>
}

function formatApiError(detail: unknown, fallback: string, status: number): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item) => {
      if (!item || typeof item !== 'object') return []
      const message = 'msg' in item && typeof item.msg === 'string' ? item.msg : ''
      const location =
        'loc' in item && Array.isArray(item.loc)
          ? item.loc
              .filter((part: unknown) => typeof part === 'string' || typeof part === 'number')
              .join('.')
          : ''
      return message ? [`${location ? `${location}: ` : ''}${message}`] : []
    })
    if (messages.length) return messages.join('；')
  }
  return fallback || `Request failed: ${status}`
}

export type TargetPlatform =
  | 'douyin' // 抖音：更偏前三秒抓注意力和明确转化动作。
  | 'xiaohongshu' // 小红书：更偏真实体验、细节展示和种草表达。

export type GenerationMode =
  | 'image_to_video' // 使用已验证商品图作为视觉锚点生成视频镜头。
  | 'text_to_video' // 仅用文本描述生成镜头，保留给后续扩展场景。

export type QualityIssueSeverity =
  | 'warning' // 非阻断提醒，方案仍可进入人工审核。
  | 'blocked' // 阻断问题，需要修复后才能通过质量门禁。

export type CreativeDecisionAction =
  | 'review_plan' // 方案通过质量门禁，可以进入人工审核。
  | 'resolve_quality_issues' // 方案已生成但仍有质量问题，需要继续修正。

export type ProductBrief = {
  product_name?: string | null
  selling_points_text: string
  target_audience_text: string
  brand_tone: string
  forbidden_words_text: string
}

export type Project = {
  id: number
  title: string
  target_platform: TargetPlatform
  language: string
  aspect_ratio: string
  duration_seconds: number
  status: string
  product_brief?: (ProductBrief & { id: number; project_id: number }) | null
  created_at: string
  updated_at: string
}

export type ProjectAsset = {
  id: number
  project_id: number
  type: string
  file_path: string
  original_filename?: string | null
  mime_type?: string | null
  size_bytes?: number | null
  created_at: string
}

export type ProductAnalysis = {
  product_summary: string
  inferred_category: string
  inferred_selling_points: string[]
  inferred_audience: string[]
  visual_evidence_count: number
  constraints: string[]
  missing_information: string[]
  readiness_score: number
}

export type ShotPlan = {
  order: number
  duration_seconds: number
  purpose: string
  visual: string
  caption: string
  generation_mode: GenerationMode
}

export type CreativeConcept = {
  concept_key: string
  title: string
  strategy: string
  hook: string
  reasoning: string
  primary_selling_point: string
  target_audience: string
  call_to_action: string
  shots: ShotPlan[]
}

export type QualityIssue = {
  severity: QualityIssueSeverity
  code: string
  message: string
  recommendation: string
}

export type QualityEvaluation = {
  overall_score: number
  dimension_scores: Record<string, number>
  passed: boolean
  issues: QualityIssue[]
  recommended_changes: string[]
}

export type CreativeDecision = {
  action: CreativeDecisionAction
  decision_reason: string
  confidence: number
  analysis: ProductAnalysis
  concepts: CreativeConcept[]
  evaluation: QualityEvaluation
  revision_count: number
}

export type CreativeRun = {
  id: number
  project_id: number
  campaign_goal?: string | null
  status: string
  action?: string | null
  confidence?: number | null
  provider: string
  model?: string | null
  revision_count: number
  result?: CreativeDecision | null
  started_at: string
  completed_at?: string | null
  error_message?: string | null
}

export type CreateCreativeRunInput = {
  projectId: number
  campaignGoal: string
}

export const api = {
  listProjects: () => request<Project[]>('/projects'),
  createProject: (payload: { title: string; target_platform: string }) =>
    request<Project>('/projects', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateProductBrief: (projectId: number, payload: ProductBrief) =>
    request<ProductBrief & { id: number; project_id: number }>(`/projects/${projectId}/product-brief`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  listAssets: (projectId: number) => request<ProjectAsset[]>(`/projects/${projectId}/assets`),
  uploadAsset: (projectId: number, file: File) => {
    const form = new FormData()
    form.set('asset_type', 'product_image')
    form.set('file', file)
    return request<ProjectAsset>(`/projects/${projectId}/assets`, {
      method: 'POST',
      body: form,
    })
  },
  listCreativeRuns: (projectId: number) =>
    request<CreativeRun[]>(`/projects/${projectId}/creative-runs`),
  createCreativeRun: ({ projectId, campaignGoal }: CreateCreativeRunInput) =>
    request<CreativeRun>(`/projects/${projectId}/creative-runs`, {
      method: 'POST',
      body: JSON.stringify({ campaign_goal: campaignGoal }),
    }),
}
