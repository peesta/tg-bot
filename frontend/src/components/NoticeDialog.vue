<script setup>
import { useRouter } from 'vue-router'
import ModalDialog from './ModalDialog.vue'
import { store } from '../store.js'

// Уведомление в начале смены: после первого за день открытия сайта.
const router = useRouter()

function goToExpiring() {
  store.notice = null
  router.push('/expiring')
}
</script>

<template>
  <ModalDialog v-if="store.notice" title="Скоро испортится" @close="store.notice = null">
    <div class="stack">
      <div v-if="store.notice.today.length">
        <h3>Сегодня заканчивается срок годности:</h3>
        <ul class="summary">
          <li v-for="item in store.notice.today" :key="item.product_name">
            <span>{{ item.product_name }}</span><b>{{ item.quantity }} шт</b>
          </li>
        </ul>
      </div>
      <div v-if="store.notice.expired.length">
        <h3>Срок годности уже истёк:</h3>
        <ul class="summary">
          <li v-for="item in store.notice.expired" :key="item.product_name">
            <span>{{ item.product_name }}</span><b>{{ item.quantity }} шт</b>
          </li>
        </ul>
      </div>
    </div>
    <template #footer>
      <button class="btn btn-secondary" type="button" @click="store.notice = null">Понятно</button>
      <button class="btn btn-primary" type="button" @click="goToExpiring">Перейти к списанию</button>
    </template>
  </ModalDialog>
</template>
