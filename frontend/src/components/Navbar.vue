<template>
  <header class="sticky top-0 z-30 glass-nav">
    <div
      class="mx-auto flex h-16 w-full max-w-6xl items-center gap-3 px-4 sm:px-6"
    >
      <button
        class="flex items-center gap-2 shrink-0"
        @click="router.push({ name: 'Home' })"
        :title="t('nav.home')"
      >
        <img
          src="../assets/downtify.svg"
          class="h-8 w-8 drop-shadow-[0_0_8px_rgba(229,160,13,0.55)]"
        />
        <span class="hidden sm:inline text-lg font-bold tracking-tight">
          Downtiplx
        </span>
      </button>

      <div class="hidden md:flex flex-1 justify-center">
        <SearchInput class="w-full max-w-md" :compact="true" />
      </div>

      <div class="ml-auto flex items-center gap-1 sm:gap-2">
        <button
          class="icon-btn"
          :class="{ 'icon-btn-active': route.name === 'List' }"
          @click="router.push({ name: 'List' })"
          :title="t('nav.library')"
        >
          <Icon icon="clarity:library-line" class="h-5 w-5" />
        </button>

        <button
          class="icon-btn"
          :class="{ 'icon-btn-active': route.name === 'Monitor' }"
          @click="router.push({ name: 'Monitor' })"
          :title="t('nav.monitor')"
        >
          <Icon icon="clarity:eye-line" class="h-5 w-5" />
        </button>

        <button
          class="icon-btn"
          :class="{ 'icon-btn-active': route.name === 'Organizer' }"
          @click="router.push({ name: 'Organizer' })"
          :title="t('nav.organizer')"
        >
          <Icon icon="clarity:organization-line" class="h-5 w-5" />
        </button>

        <button
          class="icon-btn"
          @click="
            themeMgr.setTheme(
              themeMgr.currentTheme.value === 'dark' ? 'light' : 'dark'
            )
          "
          :title="
            themeMgr.currentTheme.value === 'dark'
              ? t('nav.switchToLight')
              : t('nav.switchToDark')
          "
        >
          <Icon
            v-if="themeMgr.currentTheme.value === 'dark'"
            icon="clarity:sun-line"
            class="h-5 w-5"
          />
          <Icon v-else icon="clarity:moon-line" class="h-5 w-5" />
        </button>

        <button
          v-if="isProtected"
          class="icon-btn"
          @click="logout()"
          :title="t('nav.logout')"
        >
          <Icon icon="clarity:logout-line" class="h-5 w-5" />
        </button>

        <label
          for="settings-modal"
          class="icon-btn cursor-pointer"
          :title="t('nav.settings')"
        >
          <Icon icon="clarity:cog-line" class="h-5 w-5" />
        </label>
      </div>
    </div>

    <div class="md:hidden px-4 pb-3">
      <SearchInput :compact="true" />
    </div>
  </header>
</template>

<script setup>
import { Icon } from '@iconify/vue'
import { useRoute } from 'vue-router'
import { ref, onMounted } from 'vue'

import router from '../router'
import { useBinaryThemeManager } from '../model/theme'
import { useI18n } from '../i18n'
import API from '../model/api'

import SearchInput from './SearchInput.vue'

const route = useRoute()
const themeMgr = useBinaryThemeManager({
  newLightAlias: 'downtiplx-light',
  newDarkAlias: 'downtiplx-dark',
})
const { t } = useI18n()

const isProtected = ref(false)
onMounted(async () => {
  try {
    const res = await API.authStatus()
    isProtected.value = res.data.protected === true
  } catch {}
})

async function logout() {
  try {
    await API.authLogout()
  } catch {}
  window.location.href = '/login'
}
</script>
