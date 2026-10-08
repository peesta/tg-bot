<script setup>
import { computed } from 'vue'
import { Minus, Plus } from 'lucide-vue-next'

// Количество для планшета: быстрые кнопки, «минус/плюс» и поле с цифровой клавиатурой.
const model = defineModel({ type: Number, default: 1 })
const props = defineProps({
  max: { type: Number, default: 100000 },
  // Кнопка «Все N» — взять весь остаток (партия, морозильник).
  showAll: { type: Boolean, default: false },
})

const quick = computed(() => [1, 2, 3, 5, 10].filter((value) => value <= props.max))
const showAllChip = computed(() => props.showAll && !quick.value.includes(props.max))

function set(value) {
  const number = Math.trunc(Number(value))
  model.value = Number.isFinite(number) ? Math.min(Math.max(number, 1), props.max) : 1
}
</script>

<template>
  <div class="quantity">
    <div class="quantity-chips">
      <button
        v-for="value in quick" :key="value" class="chip" :class="{ active: model === value }"
        type="button" @click="set(value)"
      >{{ value }}</button>
      <button v-if="showAllChip" class="chip" :class="{ active: model === max }" type="button" @click="set(max)">
        Все {{ max }}
      </button>
    </div>
    <div class="stepper">
      <button class="btn btn-secondary" type="button" aria-label="Меньше" :disabled="model <= 1" @click="set(model - 1)">
        <Minus class="icon" :size="28" :stroke-width="1.75" />
      </button>
      <input
        class="input" type="number" inputmode="numeric" min="1" :max="max" :value="model"
        aria-label="Количество" @change="set($event.target.value)"
      >
      <button class="btn btn-secondary" type="button" aria-label="Больше" :disabled="model >= max" @click="set(model + 1)">
        <Plus class="icon" :size="28" :stroke-width="1.75" />
      </button>
    </div>
  </div>
</template>
