<template>
  <div class="min-h-dvh flex flex-col text-base-content">
    <router-view v-slot="{ Component, route }">
      <transition name="page" mode="out-in">
        <component :is="Component" :key="route.fullPath" />
      </transition>
    </router-view>
    <Footer />
    <Settings />
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import Footer from './components/Footer.vue'
import Settings from './components/Settings.vue'
import { useBinaryThemeManager } from './model/theme'
import API from './model/api'
import { updateFromWs } from './model/downloadStore'

const themeMgr = useBinaryThemeManager()
onMounted(() => {
  themeMgr.setLightAlias('downtiplx-light')
  themeMgr.setDarkAlias('downtiplx-dark')

  // Global persistent WS listener — keeps the Navbar badge in sync no matter
  // which page the user is on. Downloads.vue replaces this handler when mounted
  // but also calls updateFromWs itself, then restores this handler on unmount.
  API.ws_onmessage((event) => {
    try {
      updateFromWs(JSON.parse(event.data))
    } catch {}
  })
})
</script>

<style>
.page-enter-active,
.page-leave-active {
  transition:
    opacity 0.25s ease,
    transform 0.25s ease;
}
.page-enter-from,
.page-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
