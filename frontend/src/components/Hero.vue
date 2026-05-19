<template>
  <section
    class="relative flex min-h-[100dvh] flex-col items-center justify-between px-6 pt-24 pb-6 overflow-hidden"
  >
    <div aria-hidden="true" class="pointer-events-none absolute inset-0 -z-10">
      <div
        class="absolute left-1/2 top-1/4 -translate-x-1/2 h-[420px] w-[420px] rounded-full bg-primary/25 blur-[120px]"
      ></div>
      <div
        class="absolute right-10 bottom-12 h-64 w-64 rounded-full bg-primary/10 blur-3xl"
      ></div>
    </div>

    <!-- Main content -->
    <div class="relative w-full max-w-2xl text-center animate-slide-up flex-1 flex flex-col items-center justify-center">
      <div class="mx-auto mb-6 inline-flex">
        <div
          class="relative inline-flex h-24 w-24 items-center justify-center rounded-3xl surface-strong shadow-glow"
        >
          <img src="../assets/downtify.svg" class="h-14 w-14" />
        </div>
      </div>

      <h1 class="text-balance text-5xl sm:text-6xl font-bold tracking-tight">
        Downti<span class="text-primary">plx</span>
      </h1>
      <div class="mt-3 flex items-center justify-center gap-2">
        <span class="badge-soft">v{{ version }}</span>
        <span class="badge-neutral-soft">{{ t('hero.noAccount') }}</span>
      </div>
      <p
        class="mx-auto mt-5 max-w-md text-balance text-base sm:text-lg text-base-content/70"
      >
        {{ t('hero.tagline') }}
      </p>

      <!-- Search -->
      <div class="mt-10 w-full">
        <SearchInput class="w-full" />
      </div>

      <!-- App navigation buttons -->
      <div class="mt-8 grid grid-cols-2 sm:grid-cols-4 gap-3 w-full max-w-lg">
        <router-link
          to="/list"
          class="flex flex-col items-center gap-2 rounded-2xl surface py-4 px-3 hover:bg-base-100/60 transition-colors group"
        >
          <Icon icon="clarity:library-line" class="h-6 w-6 text-primary group-hover:scale-110 transition-transform" />
          <span class="text-xs font-medium text-base-content/70">{{ t('nav.library') }}</span>
        </router-link>
        <router-link
          to="/monitor"
          class="flex flex-col items-center gap-2 rounded-2xl surface py-4 px-3 hover:bg-base-100/60 transition-colors group"
        >
          <Icon icon="clarity:eye-line" class="h-6 w-6 text-primary group-hover:scale-110 transition-transform" />
          <span class="text-xs font-medium text-base-content/70">{{ t('nav.monitor') }}</span>
        </router-link>
        <router-link
          to="/organizer"
          class="flex flex-col items-center gap-2 rounded-2xl surface py-4 px-3 hover:bg-base-100/60 transition-colors group"
        >
          <Icon icon="clarity:organization-line" class="h-6 w-6 text-primary group-hover:scale-110 transition-transform" />
          <span class="text-xs font-medium text-base-content/70">{{ t('nav.organizer') }}</span>
        </router-link>
        <button
          class="flex flex-col items-center gap-2 rounded-2xl surface py-4 px-3 hover:bg-base-100/60 transition-colors group"
          @click="openSettings"
        >
          <Icon icon="clarity:settings-line" class="h-6 w-6 text-primary group-hover:scale-110 transition-transform" />
          <span class="text-xs font-medium text-base-content/70">{{ t('nav.settings') }}</span>
        </button>
      </div>
    </div>

    <!-- API status bar -->
    <div class="w-full max-w-2xl mt-8">
      <div
        class="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 rounded-2xl surface px-4 py-2.5"
      >
        <template v-if="healthLoading">
          <span class="text-xs text-base-content/40">{{ t('hero.checkingApis') }}</span>
        </template>
        <template v-else>
          <div
            v-for="(info, key) in apiHealth"
            :key="key"
            class="flex items-center gap-1.5 text-xs"
            :title="info.detail"
          >
            <span
              class="h-2 w-2 rounded-full shrink-0"
              :class="info.status === 'ok' ? 'bg-success' : 'bg-error'"
            />
            <span class="text-base-content/60 capitalize">{{ apiLabel(key) }}</span>
          </div>
          <button
            class="ml-auto text-[10px] text-base-content/30 hover:text-base-content/60 transition-colors"
            @click="loadHealth"
          >
            <Icon icon="clarity:refresh-line" class="h-3 w-3" />
          </button>
        </template>
      </div>
    </div>

    <Settings />
  </section>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Icon } from '@iconify/vue'
import SearchInput from './SearchInput.vue'
import Settings from './Settings.vue'
import API from '/src/model/api'
import { useI18n } from '../i18n'

const { t } = useI18n()
const version = ref(localStorage.getItem('version') || '2.7.0')
const apiHealth = ref({})
const healthLoading = ref(true)
const API_LABELS = {
  youtube_music: 'YouTube Music',
  spotify: 'Spotify',
  musicbrainz: 'MusicBrainz',
  acoustid: 'AcoustID',
  soundcloud: 'SoundCloud',
}

function apiLabel(key) {
  return API_LABELS[key] || key.replace(/_/g, ' ')
}

async function loadHealth() {
  healthLoading.value = true
  try {
    const res = await API.get('/api/health/apis')
    apiHealth.value = res.data || {}
  } catch {
    apiHealth.value = {}
  } finally {
    healthLoading.value = false
  }
}

function openSettings() {
  const checkbox = document.getElementById('settings-modal')
  if (checkbox) checkbox.checked = true
}

onMounted(() => {
  const v = localStorage.getItem('version')
  if (v) version.value = v
  loadHealth()
})
</script>
