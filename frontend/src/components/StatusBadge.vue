<script setup>
import { STATUS_TITLES } from '../labels.js'

defineProps({ status: { type: String, required: true } })
</script>

<template>
  <span class="badge" :class="`badge-${status}`">{{ STATUS_TITLES[status] }}</span>
</template>
