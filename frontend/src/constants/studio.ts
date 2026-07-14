export const platformOptions = [
  { label: '抖音', value: 'douyin' }, // 抖音：强调短视频转化和前三秒抓注意力。
  { label: '小红书', value: 'xiaohongshu' }, // 小红书：强调体验、细节和种草语境。
]

export const dimensionLabels: Record<string, string> = {
  product_fidelity: '商品引用覆盖', // 是否持续围绕同一商品事实和画面证据。
  platform_fit: '平台适配', // 内容结构是否符合目标平台表达习惯。
  conversion_clarity: '转化清晰度', // CTA、时长和观看路径是否清楚。
  compliance: '风险表达检查', // 是否避开风险词和用户禁用表达。
}

export const projectStatusLabels: Record<string, string> = {
  draft: '待补充', // 项目刚创建，还未保存完整商品资料。
  input_ready: '资料已保存', // 商品资料已保存，可以发起创意运行。
  running: 'Agent 运行中', // 后端正在执行 Agent 图。
  quality_blocked: '质量门禁阻断', // 方案未通过最终质量门禁。
  blocked: '质量门禁阻断', // 兼容旧状态名称。
  ready_for_review: '方案待审核', // 方案通过质量门禁，等待人工审核。
  failed: '运行失败', // 运行出现不可恢复错误。
}
