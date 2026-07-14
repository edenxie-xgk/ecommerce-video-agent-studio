<script setup lang="ts">
import { computed } from 'vue'
import {
  NAlert,
  NButton,
  NFormItem,
  NIcon,
  NInput,
  NTag,
  NUpload,
  type UploadCustomRequestOptions,
} from 'naive-ui'
import {
  BrainCircuit,
  FileImage,
  ImagePlus,
  Layers3,
  Save,
  ShieldCheck,
  Sparkles,
  Target,
} from '@lucide/vue'
import type { ProductBrief, Project, ProjectAsset } from '../api/client'

const props = defineProps<{
  project: Project | null
  assets: ProjectAsset[]
  error: string
  saving: boolean
  planning: boolean
  uploading: boolean
  busy: boolean
  brief: ProductBrief
  campaignGoal: string
}>()

const emit = defineEmits<{
  'update:campaignGoal': [value: string]
  save: []
  generate: []
  upload: [options: UploadCustomRequestOptions]
}>()

const campaignGoalModel = computed({
  get: () => props.campaignGoal,
  set: (value: string) => {
    emit('update:campaignGoal', value)
  },
})

const productAssets = computed(() =>
  props.assets.filter((asset) => asset.type === 'product_image'),
)

const platformLabel = computed(() =>
  props.project?.target_platform === 'xiaohongshu' ? '小红书' : '抖音',
)
</script>

<template>
  <section class="input-workspace">
    <n-alert v-if="error" type="error" closable>{{ error }}</n-alert>

    <template v-if="project">
      <header class="workspace-heading">
        <div>
          <span class="eyebrow">Creative Brief</span>
          <h2>{{ project.title }}</h2>
          <p>只填写确定事实。卖点组合、创意方向和镜头策略由 Agent 决定。</p>
        </div>
        <div class="project-specs">
          <n-tag type="info">{{ platformLabel }}</n-tag>
          <n-tag>{{ project.duration_seconds }}s</n-tag>
          <n-tag>{{ project.aspect_ratio }}</n-tag>
        </div>
      </header>

      <section class="form-section goal-section">
        <div class="section-title">
          <span class="section-icon"><Target :size="18" /></span>
          <div>
            <strong>本次营销目标</strong>
            <span>Agent 会根据目标选择创意角度，而不是套固定模板。</span>
          </div>
        </div>
        <n-input
          v-model:value="campaignGoalModel"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 4 }"
          :disabled="busy"
          placeholder="例如：让通勤人群理解便携优势，并愿意点击商品详情"
        />
      </section>

      <section class="form-section">
        <div class="section-title">
          <span class="section-icon blue"><Layers3 :size="18" /></span>
          <div>
            <strong>商品事实</strong>
            <span>留空的非必要字段可以由 Agent 推断并标记置信度。</span>
          </div>
        </div>
        <div class="form-grid">
          <n-form-item label="准确商品名称" required>
            <n-input
              v-model:value="brief.product_name"
              :disabled="busy"
              placeholder="例如：便携保温杯"
            />
          </n-form-item>
          <n-form-item label="已确认卖点">
            <n-input
              v-model:value="brief.selling_points_text"
              :disabled="busy"
              placeholder="用逗号分隔，例如：轻便易携、杯盖密封"
            />
          </n-form-item>
          <n-form-item label="已知目标人群">
            <n-input
              v-model:value="brief.target_audience_text"
              :disabled="busy"
              placeholder="例如：通勤上班族、学生"
            />
          </n-form-item>
          <n-form-item label="品牌语气">
            <n-input
              v-model:value="brief.brand_tone"
              :disabled="busy"
              placeholder="例如：真实克制、精致高级"
            />
          </n-form-item>
        </div>
        <n-form-item label="必须避免的表达">
          <n-input
            v-model:value="brief.forbidden_words_text"
            :disabled="busy"
            placeholder="例如：永久、治疗、百分百"
          />
        </n-form-item>
      </section>

      <section class="form-section">
        <div class="section-title">
          <span class="section-icon amber"><ImagePlus :size="18" /></span>
          <div>
            <strong>商品图片素材</strong>
            <span>至少一张主图。支持 JPEG、PNG、WebP，单张不超过 10 MB。</span>
          </div>
          <n-tag size="small" :type="productAssets.length ? 'success' : 'warning'">
            {{ productAssets.length }}/5
          </n-tag>
        </div>

        <n-upload
          accept="image/*"
          :show-file-list="false"
          :custom-request="(options) => emit('upload', options)"
          :disabled="busy || productAssets.length >= 5"
        >
          <button class="upload-zone" type="button" :disabled="busy || productAssets.length >= 5">
            <FileImage :size="22" />
            <span>
              <strong>{{ uploading ? '正在上传商品图片' : '上传商品图片' }}</strong>
              <small>文件通过完整解码校验后才会加入项目</small>
            </span>
          </button>
        </n-upload>

        <div v-if="productAssets.length" class="asset-list">
          <span v-for="asset in productAssets" :key="asset.id" class="asset-chip">
            <FileImage :size="14" />
            {{ asset.original_filename ?? asset.file_path }}
          </span>
        </div>
      </section>

      <footer class="workspace-actions">
        <div>
          <ShieldCheck :size="17" />
          真实视频生成仍需人工确认，Agent 只负责制定和评估方案。
        </div>
        <n-button :loading="saving" :disabled="busy" @click="emit('save')">
          <template #icon><n-icon :component="Save" /></template>
          保存事实
        </n-button>
        <n-button
          type="primary"
          size="large"
          :loading="planning"
          :disabled="busy"
          @click="emit('generate')"
        >
          <template #icon><n-icon :component="BrainCircuit" /></template>
          让 Agent 制定方案
        </n-button>
      </footer>
    </template>

    <div v-else class="workspace-empty">
      <Sparkles :size="30" />
      <h2>创建项目后开始</h2>
      <p>商品图和营销目标是 Agent 做出有效决策的最小输入。</p>
    </div>
  </section>
</template>
