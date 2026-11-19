<script setup lang="ts">
import type { Result } from '../types'
import ReportContent from '../components/ReportContent.vue'
import ThemeToggle from '../components/ThemeToggle.vue'
import { kindLabel, profileLabel } from '../utils/materials'
import { formatDateTime } from '../utils/date'

defineProps<{ filename?: string; result?: Result; error?: string; brandMark: string }>()
</script>

<template>
  <a class="skip-link" href="#main-content">跳到主要内容</a>
  <main id="main-content" class="standalone-report" tabindex="-1">
    <header class="report-brand">
      <img :src="brandMark" alt="" width="48" height="48" />
      <div><strong>Formatly</strong></div>
      <ThemeToggle />
    </header>
    <div class="page-heading result-heading report-heading">
      <div>
        <h1>{{ filename || '论文格式检测报告' }}</h1>
        <p v-if="result"><span v-if="result.profile_snapshot">{{ profileLabel(result.profile_snapshot) }} · </span><span v-if="result.kind">{{ kindLabel(result.kind) }} · </span><span>{{ formatDateTime(result.created_at) }}</span></p>
      </div>
    </div>
    <p v-if="error" class="notice error-notice" role="alert">{{ error }}</p>
    <ReportContent v-else-if="result" :result="result" />
  </main>
</template>
