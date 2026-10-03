<script setup>
import BatchPicker from '../components/BatchPicker.vue'
import PageHeader from '../components/PageHeader.vue'
</script>

<template>
  <PageHeader title="Списание" subtitle="Выберите партию, укажите причину и количество" />
  <BatchPicker only="write_off" />
</template>
