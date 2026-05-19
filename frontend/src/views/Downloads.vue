<template>
  <div class="min-h-screen">
    <Navbar />
    <Settings />

    <AuditModal
      :show="auditModal"
      :track-id="auditTrackId"
      :track-name="auditTrackName"
      @close="auditModal = false"
    />

    <div class="mx-auto max-w-4xl px-4 py-8 sm:px-6">
      <!-- Header -->
      <div class="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 class="text-2xl font-bold tracking-tight">
            {{ t('library.title') }}
          </h1>
          <p class="mt-1 text-sm text-base-content/60">
            {{ t('library.subtitle') }}
          </p>
        </div>
        <button
          class="btn btn-sm h-11 px-5 rounded-full border-white/10 bg-base-100/85 hover:bg-base-100"
          @click="refresh"
          :disabled="loading"
        >
          <span v-if="loading" class="loading loading-spinner loading-xs mr-2" />
          <Icon v-else icon="clarity:refresh-line" class="h-4 w-4 mr-2" />
          {{ t('common.refresh') }}
        </button>
      </div>

      <!-- ── Section 1: Active Downloads ── -->
      <section v-if="activeDownloads.length > 0" class="mb-6">
        <h2
          class="mb-2 text-xs font-semibold uppercase tracking-wider text-primary flex items-center gap-1.5"
        >
          <span class="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
          {{ t('library.downloading') }}
        </h2>
        <ul class="space-y-2">
          <li
            v-for="job in activeDownloads"
            :key="job.song_id"
            class="surface rounded-2xl p-3 sm:p-4 flex items-center gap-3"
          >
            <div
              class="h-11 w-11 shrink-0 rounded-xl bg-primary/10 text-primary flex items-center justify-center"
            >
              <span class="loading loading-spinner loading-sm" />
            </div>
            <div class="flex-1 min-w-0">
              <span class="text-sm font-medium truncate block">
                {{ job.song?.name || job.song?.title || job.song_id }}
              </span>
              <div class="mt-1 flex items-center gap-2">
                <progress
                  class="progress progress-primary h-1 flex-1"
                  :value="job.progress"
                  max="100"
                />
                <span class="text-xs text-base-content/40 shrink-0">
                  {{ Math.round(job.progress) }}%
                </span>
              </div>
              <span v-if="job.message" class="text-xs text-base-content/40 truncate block">
                {{ job.message }}
              </span>
            </div>
          </li>
        </ul>
      </section>

      <!-- ── Section 2: Organizer Running ── -->
      <section v-if="organizingJobs.length > 0" class="mb-6">
        <h2
          class="mb-2 text-xs font-semibold uppercase tracking-wider text-warning flex items-center gap-1.5"
        >
          <Icon icon="clarity:organization-line" class="h-3.5 w-3.5 animate-pulse" />
          {{ t('library.organizing') }}
        </h2>
        <ul class="space-y-2">
          <li
            v-for="job in organizingJobs"
            :key="job.track_id || job.song_name"
            class="surface rounded-2xl p-3 sm:p-4 flex items-center gap-3"
          >
            <div
              class="h-11 w-11 shrink-0 rounded-xl bg-warning/10 text-warning flex items-center justify-center"
            >
              <Icon icon="clarity:nodes-line" class="h-5 w-5" />
            </div>
            <div class="flex-1 min-w-0">
              <span class="text-sm font-medium truncate block">
                {{ job.song_name }}
              </span>
              <span class="text-xs text-warning/70">
                {{ t('library.organizerStep', { step: job.step }) }}
                <span class="text-base-content/40 ml-1">— {{ job.step_name }}</span>
              </span>
            </div>
          </li>
        </ul>
      </section>

      <!-- ── Section 3: Finished ── -->
      <section>
        <h2
          v-if="activeDownloads.length > 0 || organizingJobs.length > 0"
          class="mb-2 text-xs font-semibold uppercase tracking-wider text-base-content/50 flex items-center gap-1.5"
        >
          <Icon icon="clarity:check-circle-line" class="h-3.5 w-3.5" />
          {{ t('library.finished') }}
        </h2>

        <!-- Search bar -->
        <div class="mb-4 relative">
          <Icon
            icon="clarity:search-line"
            class="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-base-content/40 pointer-events-none"
          />
          <input
            v-model="searchInput"
            type="text"
            :placeholder="t('library.search')"
            class="w-full rounded-xl bg-base-100/85 border border-white/10 focus:border-primary/60 focus:outline-none pl-10 pr-4 py-2.5 text-sm"
          />
        </div>

        <!-- Error -->
        <div
          v-if="error"
          class="surface rounded-2xl p-4 mb-4 flex gap-3 items-center text-sm text-error"
        >
          <Icon icon="clarity:exclamation-circle-line" class="h-5 w-5 shrink-0" />
          <span>{{ error }}</span>
        </div>

        <!-- Success toast -->
        <Transition name="toast">
          <div
            v-if="successMsg"
            class="surface rounded-2xl p-4 mb-4 flex gap-3 items-center text-sm text-primary"
          >
            <Icon icon="clarity:check-circle-line" class="h-5 w-5 shrink-0" />
            <span>{{ successMsg }}</span>
          </div>
        </Transition>

        <!-- Loading skeleton -->
        <div v-if="loading && items.length === 0" class="space-y-3">
          <div v-for="n in 5" :key="n" class="skeleton h-16 rounded-2xl" />
        </div>

        <!-- Empty state -->
        <div
          v-else-if="!loading && items.length === 0"
          class="surface rounded-2xl p-12 flex flex-col items-center text-center"
        >
          <Icon icon="clarity:list-line" class="h-12 w-12 text-base-content/20 mb-4" />
          <p class="text-base-content/50 text-sm">{{ t('library.empty') }}</p>
          <p class="text-base-content/40 text-xs mt-1">{{ t('library.emptyHint') }}</p>
        </div>

        <!-- Track list -->
        <ul v-else class="space-y-2">
          <li
            v-for="item in items"
            :key="item.id"
            class="surface rounded-2xl p-3 sm:p-4 flex items-start gap-3"
          >
            <!-- Icon -->
            <div
              class="h-11 w-11 shrink-0 rounded-xl bg-primary/10 text-primary flex items-center justify-center mt-0.5"
            >
              <Icon icon="clarity:music-note-line" class="h-5 w-5" />
            </div>

            <!-- Info -->
            <div class="flex-1 min-w-0">
              <span class="text-sm font-medium truncate block">
                {{ displayFilename(item) }}
              </span>
              <span class="text-xs text-base-content/40 flex items-center gap-2 mt-0.5 flex-wrap">
                <span v-if="item.playlist_name" class="text-primary/70">
                  <Icon
                    icon="clarity:playlist-line"
                    class="inline h-3 w-3 mr-0.5 align-text-top"
                  />{{ item.playlist_name }}
                </span>
                <span v-else class="text-base-content/30">{{ t('library.direct') }}</span>
                <span>·</span>
                <span>{{ relativeDate(item.downloaded_at) }}</span>
                <span v-if="item.filename" class="text-base-content/30">
                  {{ fileExt(item.filename) }}
                </span>
              </span>

              <!-- Metadata: final vs orig -->
              <div
                v-if="item.genre || item.artist || item.album"
                class="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5"
              >
                <span
                  v-if="item.artist"
                  class="text-xs text-base-content/60"
                  :title="item.orig_artist && item.orig_artist !== item.artist ? `Original: ${item.orig_artist}` : undefined"
                >
                  <span class="text-base-content/30 mr-0.5">Artist</span>
                  {{ item.artist }}
                  <span
                    v-if="item.orig_artist && item.orig_artist !== item.artist"
                    class="text-base-content/30 text-[10px]"
                  >← {{ item.orig_artist }}</span>
                </span>
                <span
                  v-if="item.album"
                  class="text-xs text-base-content/60"
                  :title="item.orig_album && item.orig_album !== item.album ? `Original: ${item.orig_album}` : undefined"
                >
                  <span class="text-base-content/30 mr-0.5">Album</span>
                  {{ item.album }}
                  <span
                    v-if="item.orig_album && item.orig_album !== item.album"
                    class="text-base-content/30 text-[10px]"
                  >← {{ item.orig_album }}</span>
                </span>
                <span
                  v-if="item.genre"
                  class="text-xs text-base-content/60"
                  :title="item.orig_genre && item.orig_genre !== item.genre ? `Original: ${item.orig_genre}` : undefined"
                >
                  <span class="text-base-content/30 mr-0.5">Genre</span>
                  {{ item.genre }}
                  <span
                    v-if="item.orig_genre && item.orig_genre !== item.genre"
                    class="text-base-content/30 text-[10px]"
                  >← {{ item.orig_genre }}</span>
                </span>
              </div>
            </div>

            <!-- Audit button — always visible -->
            <button
              class="icon-btn text-base-content/30 hover:text-primary hover:bg-primary/10 shrink-0 mt-0.5"
              @click="openAudit(item)"
              :title="t('audit.tooltip')"
            >
              <Icon icon="clarity:eye-line" class="h-4 w-4" />
            </button>
            <button
              class="icon-btn text-error/70 hover:text-error hover:bg-error/10 shrink-0 mt-0.5"
              :disabled="deleting[item.id] === true"
              @click="onDelete(item)"
              :title="t('library.deleteFile')"
            >
              <span v-if="deleting[item.id] === true" class="loading loading-spinner loading-xs" />
              <Icon v-else icon="clarity:trash-line" class="h-4 w-4" />
            </button>
          </li>
        </ul>

        <!-- Pagination -->
        <nav
          v-if="totalPages > 1"
          class="mt-8 flex items-center justify-center gap-1 flex-wrap"
        >
          <button
            class="icon-btn"
            :disabled="currentPage === 1"
            @click="goToPage(currentPage - 1)"
            :title="t('common.previousPage')"
          >
            <Icon icon="clarity:angle-line" class="h-4 w-4 rotate-[-90deg]" />
          </button>
          <button
            v-for="page in visiblePages"
            :key="page"
            class="h-10 min-w-[2.5rem] rounded-full px-3 text-sm font-medium transition-colors"
            :class="
              page === currentPage
                ? 'bg-primary text-primary-content shadow-glow-sm'
                : 'text-base-content/70 hover:text-base-content hover:bg-white/10'
            "
            @click="goToPage(page)"
          >
            {{ page }}
          </button>
          <button
            class="icon-btn"
            :disabled="currentPage === totalPages"
            @click="goToPage(currentPage + 1)"
            :title="t('common.nextPage')"
          >
            <Icon icon="clarity:angle-line" class="h-4 w-4 rotate-90" />
          </button>
        </nav>

        <!-- Count footer -->
        <p v-if="total > 0" class="mt-6 text-xs text-base-content/40 text-center">
          {{
            total === 1
              ? t('library.countOne', { count: total })
              : t('library.countMany', { count: total })
          }}
        </p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { Icon } from '@iconify/vue'
import Navbar from '/src/components/Navbar.vue'
import Settings from '/src/components/Settings.vue'
import AuditModal from '/src/components/AuditModal.vue'
import API from '/src/model/api'
import { useI18n } from '/src/i18n'

const PAGE_SIZE = 20
const { t } = useI18n()

// ── Section 3: Finished (List of Truth) ──────────────────────────────────────
const items = ref([])
const total = ref(0)
const totalPages = ref(1)
const currentPage = ref(1)
const searchInput = ref('')
const loading = ref(false)
const error = ref('')
const successMsg = ref('')
const deleting = ref({})

// ── Section 1: Active Downloads ──────────────────────────────────────────────
const activeDownloads = ref([])

// ── Section 2: Organizer pipeline ────────────────────────────────────────────
const organizingJobs = ref([])

// ── Audit modal ───────────────────────────────────────────────────────────────
const auditModal = ref(false)
const auditTrackId = ref('')
const auditTrackName = ref('')

function openAudit(item) {
  auditTrackId.value = item.track_spotify_id || ''
  auditTrackName.value = displayFilename(item) || item.track_spotify_id || ''
  auditModal.value = true
}

// ── WebSocket handler ─────────────────────────────────────────────────────────
function handleWsMessage(event) {
  let msg
  try {
    msg = JSON.parse(event.data)
  } catch {
    return
  }

  const msgType = msg.type || ''

  if (msgType === 'organizer') {
    const id = msg.track_id || msg.song_name || '_'
    const existing = organizingJobs.value.find(
      (j) => j.track_id === id || j.song_name === msg.song_name
    )
    if (existing) {
      existing.step = msg.step
      existing.step_name = msg.step_name
    } else {
      organizingJobs.value.push({
        track_id: id,
        song_name: msg.song_name || id,
        step: msg.step,
        step_name: msg.step_name,
      })
    }
    return
  }

  if (msgType === 'organizer_done') {
    const id = msg.track_id || msg.song_name || '_'
    organizingJobs.value = organizingJobs.value.filter(
      (j) => j.track_id !== id && j.song_name !== msg.song_name
    )
    // Refresh finished list
    loadTruth()
    return
  }

  // Download messages (no explicit type, use status field)
  const status = msg.status
  if (!status) return

  const song = msg.song || {}
  const songId = song.song_id || song.url || JSON.stringify(song)

  if (status === 'downloading') {
    const existing = activeDownloads.value.find((j) => j.song_id === songId)
    if (existing) {
      existing.progress = msg.progress ?? existing.progress
      existing.message = msg.message ?? existing.message
    } else {
      activeDownloads.value.push({
        song_id: songId,
        song,
        progress: msg.progress ?? 0,
        message: msg.message ?? '',
      })
    }

    // Move from downloading → organizing (remove from section 1)
    organizingJobs.value = organizingJobs.value.filter((j) => j.track_id !== songId)
  } else if (status === 'done' || status === 'error') {
    activeDownloads.value = activeDownloads.value.filter((j) => j.song_id !== songId)
    if (status === 'done') {
      // Organizer will pick it up; refresh will happen on organizer_done
      // But also refresh now for non-organized downloads
      setTimeout(loadTruth, 1500)
    }
  }
}

let _prevOnMessage = null
onMounted(() => {
  _prevOnMessage = API.ws_onmessage(handleWsMessage)
  loadTruth()
})
onUnmounted(() => {
  if (_prevOnMessage) API.ws_onmessage(_prevOnMessage)
})

// ── List of Truth ─────────────────────────────────────────────────────────────
let searchTimeout = null

const visiblePages = computed(() => {
  const pages = []
  const max = totalPages.value
  const cur = currentPage.value
  const delta = 2
  for (let i = Math.max(1, cur - delta); i <= Math.min(max, cur + delta); i++) {
    pages.push(i)
  }
  return pages
})

watch(searchInput, () => {
  clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    currentPage.value = 1
    loadTruth()
  }, 300)
})

async function loadTruth() {
  loading.value = true
  error.value = ''
  try {
    const res = await API.listTruth(searchInput.value, currentPage.value, PAGE_SIZE)
    items.value = res.data.items || []
    total.value = res.data.total || 0
    totalPages.value = res.data.pages || 1
  } catch {
    error.value = t('library.failedLoad')
  } finally {
    loading.value = false
  }
}

function refresh() {
  loadTruth()
}

function goToPage(page) {
  currentPage.value = page
  loadTruth()
}

async function onDelete(item) {
  if (!confirm(t('library.deletePrompt'))) return
  deleting.value = { ...deleting.value, [item.id]: true }
  try {
    await API.deleteTruth(item.id)
    items.value = items.value.filter((i) => i.id !== item.id)
    total.value = Math.max(0, total.value - 1)
    showSuccess(t('library.deleteSuccess'))
  } catch {
    error.value = t('library.failedDelete')
  } finally {
    deleting.value = { ...deleting.value, [item.id]: false }
  }
}

function showSuccess(msg) {
  successMsg.value = msg
  setTimeout(() => {
    successMsg.value = ''
  }, 3000)
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function displayFilename(item) {
  if (item.title) return item.title
  if (item.display_name) return item.display_name
  const filename = item.filename
  if (!filename) return item.track_spotify_id || ''
  const slash = filename.lastIndexOf('/')
  const name = slash >= 0 ? filename.slice(slash + 1) : filename
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(0, dot) : name
}

function fileExt(filename) {
  if (!filename) return ''
  const dot = filename.lastIndexOf('.')
  return dot > 0 ? filename.slice(dot + 1).toUpperCase() : ''
}

function relativeDate(isoStr) {
  if (!isoStr) return ''
  try {
    const d = new Date(isoStr)
    const diff = (Date.now() - d.getTime()) / 1000
    if (diff < 60) return 'just now'
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    if (diff < 2592000) return `${Math.floor(diff / 86400)}d ago`
    return d.toLocaleDateString()
  } catch {
    return isoStr
  }
}
</script>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition:
    opacity 0.3s,
    transform 0.3s;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
