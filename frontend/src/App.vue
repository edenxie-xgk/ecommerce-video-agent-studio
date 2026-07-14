<script setup lang="ts">
import { NConfigProvider, NMessageProvider, type GlobalThemeOverrides } from 'naive-ui'
import { Sparkles } from '@lucide/vue'
import StudioPage from './pages/StudioPage.vue'

const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#0F766E',
    primaryColorHover: '#0D9488',
    primaryColorPressed: '#115E59',
    primaryColorSuppl: '#2563EB',
    borderRadius: '7px',
    fontFamily:
      'Lato, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  },
  Button: {
    borderRadiusMedium: '7px',
    borderRadiusLarge: '7px',
  },
  Input: {
    borderRadius: '7px',
  },
}
</script>

<template>
  <n-config-provider :theme-overrides="themeOverrides">
    <n-message-provider>
      <div class="app-shell">
        <header class="app-header">
          <div class="brand-lockup">
            <span class="brand-mark"><Sparkles :size="18" /></span>
            <div>
              <strong>Commerce Creative Agent</strong>
              <span>电商短视频创意决策与审核</span>
            </div>
          </div>
          <div class="header-status">
            <span class="status-dot"></span>
            受约束决策模式
          </div>
        </header>
        <StudioPage />
      </div>
    </n-message-provider>
  </n-config-provider>
</template>
