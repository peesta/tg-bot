<script setup>
defineProps({ icon: { type: [Object, Function], required: true }, text: { type: String, required: true } })
</script>

<template>
  <div class="empty">
    <component :is="icon" class="icon" :size="44" :stroke-width="1.5" />
    <p>{{ text }}</p>
    <slot />
  </div>
</template>
