<script setup>
import BatchPicker from '../components/BatchPicker.vue'
import PageHeader from '../components/PageHeader.vue'
</script>

<template>
  <PageHeader title="Продажа" subtitle="Выберите партию и укажите, сколько продано" />
  <BatchPicker only="sale" />
</template>
