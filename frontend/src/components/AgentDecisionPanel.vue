<script setup lang="ts">
import { computed } from 'vue'
import { NAlert, NProgress, NTag } from 'naive-ui'
import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  CircleGauge,
  Lightbulb,
} from '@lucide/vue'
import type { CreativeRun } from '../api/client'
import { dimensionLabels, projectStatusLabels } from '../constants/studio'

const props = defineProps<{
  run: CreativeRun | null
  planning: boolean
  busy: boolean
}>()

const decision = computed(() => props.run?.result ?? null)
const qualityBlocked = computed(
  () =>
    props.run?.status === 'quality_blocked' ||
    props.run?.status === 'blocked' ||
    decision.value?.action === 'resolve_quality_issues' ||
    (decision.value !== null && !decision.value.evaluation.passed),
)
const runLoading = computed(
  () => props.planning || (props.run?.status === 'running' && decision.value === null),
)

function runTagType(status: string): 'success' | 'warning' | 'error' | 'info' {
  if (status === 'ready_for_review') return 'success'
  if (status === 'failed' || status === 'quality_blocked' || status === 'blocked') return 'error'
  if (status === 'running') return 'info'
  return 'warning'
}

function scoreStatus(score: number) {
  if (score >= 85) return 'success'
  if (score >= 70) return 'warning'
  return 'error'
}
</script>

<template>
  <aside class="decision-workspace">
    <header class="decision-heading">
      <div>
        <span class="eyebrow">Agent Decision</span>
        <h2>创意决策</h2>
      </div>
      <n-tag v-if="run" :type="runTagType(run.status)">
        {{ projectStatusLabels[run.status] ?? run.status }}
      </n-tag>
    </header>

    <div v-if="runLoading" class="decision-loading" role="status" aria-live="polite">
      <span class="thinking-indicator"><i></i><i></i><i></i></span>
      <strong>{{ planning ? '正在分析商品事实和平台策略' : '创意任务仍在运行' }}</strong>
      <span>生成方案后会检查商品引用、转化结构和风险表达。</span>
    </div>

    <n-alert
      v-else-if="run?.status === 'failed'"
      class="run-state-alert"
      type="error"
      title="创意任务执行失败"
    >
      {{ run.error_message || '运行未能完成，请检查服务状态后重新发起。' }}
    </n-alert>

    <n-alert
      v-else-if="run && (run.status === 'quality_blocked' || run.status === 'blocked') && !decision"
      class="run-state-alert"
      type="error"
      title="质量门禁已阻断"
    >
      {{ run.error_message || '当前运行没有返回可审核的质量结果。' }}
    </n-alert>

    <template v-else-if="decision">
      <section
        class="decision-summary"
        :class="{ blocked: qualityBlocked }"
      >
        <span class="summary-icon">
          <AlertTriangle v-if="qualityBlocked" :size="20" />
          <CheckCircle2 v-else :size="20" />
        </span>
        <div>
          <strong>
            {{
              qualityBlocked
                ? '质量门禁未通过，需先处理阻断项'
                : '方案已可进入人工审核'
            }}
          </strong>
          <p>{{ decision.decision_reason }}</p>
        </div>
        <span class="confidence">{{ Math.round(decision.confidence * 100) }}% 置信度</span>
      </section>

      <template>
        <section class="analysis-panel">
          <div class="panel-title-row">
            <div>
              <span class="eyebrow">Product Analysis</span>
              <h3>{{ decision.analysis.product_summary }}</h3>
            </div>
            <div class="readiness-score">
              <strong>{{ decision.analysis.readiness_score }}</strong>
              <span>资料就绪度</span>
            </div>
          </div>
          <p>{{ decision.analysis.inferred_category }}</p>
          <div class="analysis-group">
            <span>Agent 采用的卖点</span>
            <div>
              <n-tag
                v-for="item in decision.analysis.inferred_selling_points"
                :key="item"
                size="small"
                type="info"
              >
                {{ item }}
              </n-tag>
            </div>
          </div>
          <div class="analysis-group">
            <span>目标人群判断</span>
            <div>
              <n-tag
                v-for="item in decision.analysis.inferred_audience"
                :key="item"
                size="small"
              >
                {{ item }}
              </n-tag>
            </div>
          </div>
        </section>

        <section class="concept-section">
          <div class="section-heading-row">
            <div>
              <span class="eyebrow">Creative Options</span>
              <h3>三套差异化方案</h3>
            </div>
            <n-tag size="small">{{ decision.concepts.length }} 个方向</n-tag>
          </div>

          <article
            v-for="(concept, index) in decision.concepts"
            :key="concept.concept_key"
            class="concept-card"
          >
            <header>
              <span class="concept-number">0{{ index + 1 }}</span>
              <div>
                <h4>{{ concept.title }}</h4>
                <p>{{ concept.strategy }}</p>
              </div>
            </header>

            <blockquote>{{ concept.hook }}</blockquote>

            <div class="concept-meta">
              <span><strong>核心卖点</strong>{{ concept.primary_selling_point }}</span>
              <span><strong>目标人群</strong>{{ concept.target_audience }}</span>
            </div>

            <div class="shot-list">
              <div v-for="shot in concept.shots" :key="shot.order" class="shot-row">
                <span class="shot-time">{{ shot.duration_seconds }}s</span>
                <div>
                  <strong>{{ shot.purpose }}</strong>
                  <p>{{ shot.visual }}</p>
                  <small>{{ shot.caption }}</small>
                </div>
                <n-tag
                  size="tiny"
                  :type="shot.generation_mode === 'image_to_video' ? 'success' : 'info'"
                >
                  {{ shot.generation_mode === 'image_to_video' ? '商品展示' : '场景动作' }}
                </n-tag>
              </div>
            </div>

            <footer>
              <span><Lightbulb :size="15" /> {{ concept.reasoning }}</span>
              <strong>{{ concept.call_to_action }}</strong>
            </footer>
          </article>
        </section>

        <section class="evaluation-panel">
          <div class="section-heading-row">
            <div>
              <span class="eyebrow">Quality Gate</span>
              <h3>自动质量预检</h3>
            </div>
            <div class="overall-score" :class="{ passed: decision.evaluation.passed }">
              <CircleGauge :size="18" />
              {{ decision.evaluation.overall_score }}
            </div>
          </div>

          <div class="score-list">
            <div
              v-for="(score, key) in decision.evaluation.dimension_scores"
              :key="key"
              class="score-row"
            >
              <span>{{ dimensionLabels[String(key)] ?? key }}</span>
              <n-progress
                type="line"
                :percentage="score"
                :status="scoreStatus(score)"
                :show-indicator="false"
                :height="7"
              />
              <strong>{{ score }}</strong>
            </div>
          </div>

          <div v-if="decision.evaluation.issues.length" class="issue-list">
            <article
              v-for="issue in decision.evaluation.issues"
              :key="`${issue.code}-${issue.message}`"
              :class="['issue-row', issue.severity]"
            >
              <AlertTriangle :size="16" />
              <div>
                <strong>{{ issue.message }}</strong>
                <span>{{ issue.recommendation }}</span>
              </div>
            </article>
          </div>
          <div v-else-if="!decision.evaluation.passed" class="issue-list">
            <article class="issue-row blocked">
              <AlertTriangle :size="16" />
              <div>
                <strong>质量门禁未通过，但未返回具体阻断原因。</strong>
                <span>请重新运行评估或检查服务端质量规则。</span>
              </div>
            </article>
          </div>
          <div v-else class="evaluation-ok">
            <CheckCircle2 :size="17" />
            自动质量门禁已通过，可以进入人工审核。
          </div>

          <p v-if="decision.revision_count" class="revision-note">
            Agent 已根据首次评估自动修订 {{ decision.revision_count }} 次。
          </p>
        </section>
      </template>
    </template>

    <div v-else class="decision-empty">
      <BrainCircuit :size="30" />
      <h3>等待创意任务</h3>
      <p>保存商品事实并运行 Agent 后，这里会显示决策理由、创意方案和质量评估。</p>
    </div>
  </aside>
</template>
