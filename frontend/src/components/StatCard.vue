<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { displayCount } from '../utils/numbers'
defineProps<{ label: string; value: number|string; tone?: string; icon?: string }>();
</script>
<template><article class="stat-card"><span class="stat-icon" :class="tone"><AppIcon :name="icon || 'file'" /></span><div><span class="stat-label">{{ label }}</span><strong :title="String(value)" :aria-label="String(value)">{{ displayCount(value) }}</strong></div></article></template>

