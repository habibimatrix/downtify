<template>
  <div class="min-h-screen">
    <Navbar />
    <Settings />

    <div class="mx-auto max-w-4xl px-4 py-8 sm:px-6">
      <!-- Header -->
      <div class="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 class="text-2xl font-bold tracking-tight">
            {{ t('organizer.title') }}
          </h1>
          <p class="mt-1 text-sm text-base-content/60">
            {{ t('organizer.subtitle') }}
          </p>
        </div>
        <div class="flex items-center gap-3">
          <Transition name="status">
            <span
              v-if="isDirty && !isSaved"
              class="text-xs text-base-content/50 flex items-center gap-1"
            >
              <span class="inline-block h-1.5 w-1.5 rounded-full bg-warning" />
              {{ t('organizer.unsaved') }}
            </span>
          </Transition>
          <button
            class="btn btn-primary btn-sm h-11 px-6 rounded-full"
            :disabled="saving"
            @click="saveRules"
          >
            <span
              v-if="saving"
              class="loading loading-spinner loading-xs mr-2"
            />
            {{ t('organizer.save') }}
          </button>
        </div>
      </div>

      <!-- Save result toast -->
      <Transition name="toast">
        <div
          v-if="saveResult"
          class="surface rounded-2xl p-4 mb-6 flex gap-3 items-center text-sm"
          :class="saveResult === 'ok' ? 'text-primary' : 'text-error'"
        >
          <Icon
            :icon="
              saveResult === 'ok'
                ? 'clarity:check-circle-line'
                : 'clarity:exclamation-circle-line'
            "
            class="h-5 w-5 shrink-0"
          />
          <span>{{
            saveResult === 'ok'
              ? t('organizer.saved')
              : t('organizer.saveError')
          }}</span>
        </div>
      </Transition>

      <!-- Loading skeleton -->
      <div v-if="loading" class="space-y-3">
        <div class="skeleton h-10 rounded-2xl" />
        <div v-for="n in 8" :key="n" class="skeleton h-12 rounded-xl" />
      </div>

      <template v-else>
        <!-- ── Tab navigation ─────────────────────────────────────────────── -->
        <div class="tabs tabs-border mb-8">
          <button
            class="tab"
            :class="{ 'tab-active': activeTab === 'genre' }"
            @click="activeTab = 'genre'"
          >
            {{ t('organizer.tabGenreRules') }}
          </button>
          <button
            class="tab"
            :class="{ 'tab-active': activeTab === 'artist' }"
            @click="activeTab = 'artist'"
          >
            {{ t('organizer.tabArtistSettings') }}
          </button>
        </div>

        <!-- ══════════════════════════════════════════════════════════ -->
        <!-- TAB 2: ARTIST SETTINGS                                   -->
        <!-- ══════════════════════════════════════════════════════════ -->
        <div v-show="activeTab === 'artist'">

        <!-- ══════════════════════════════════════════════════════════ -->
        <!-- ARTIST → GENRE RULES (highest priority)                  -->
        <!-- ══════════════════════════════════════════════════════════ -->
        <section class="mb-10">
          <div class="mb-3">
            <h2 class="text-base font-semibold">
              {{ t('organizer.artistGenreRules') }}
            </h2>
            <p class="text-xs text-base-content/50 mt-0.5">
              {{ t('organizer.artistGenreRulesHint') }}
            </p>
          </div>

          <!-- Add form -->
          <div
            class="surface rounded-2xl p-3 mb-3 flex flex-wrap gap-2 items-center"
          >
            <input
              v-model="newArtistPattern"
              type="text"
              :placeholder="t('organizer.newArtistPattern')"
              class="flex-1 min-w-[140px] rounded-xl bg-base-100/85 border border-white/10 focus:border-primary/60 focus:outline-none px-3 py-2 text-sm"
              @keydown.enter="addArtistGenreRule"
            />
            <Icon
              icon="clarity:arrow-line"
              class="h-4 w-4 text-base-content/30 shrink-0"
            />
            <div class="flex-1 min-w-[140px] relative">
              <input
                v-model="newArtistGenre"
                type="text"
                list="ag-folder-list"
                :placeholder="t('organizer.newGenre')"
                class="w-full rounded-xl bg-base-100/85 border border-white/10 focus:border-primary/60 focus:outline-none px-3 py-2 text-sm"
                @keydown.enter="addArtistGenreRule"
              />
              <datalist id="ag-folder-list">
                <option v-for="f in availableFolders" :key="f" :value="f" />
              </datalist>
            </div>
            <button
              class="btn btn-sm h-10 px-4 rounded-xl border-white/10 bg-base-100/85 hover:bg-primary/10 hover:border-primary/50 hover:text-primary transition-colors"
              @click="addArtistGenreRule"
            >
              <Icon icon="clarity:plus-line" class="h-4 w-4 mr-1" />
              {{ t('organizer.addArtistGenreRule') }}
            </button>
          </div>

          <!-- List -->
          <div class="surface rounded-2xl overflow-hidden">
            <div
              v-if="artistGenreRules.length === 0"
              class="p-8 text-center text-sm text-base-content/40"
            >
              No artist→genre rules yet. Add one above.
            </div>
            <ul v-else class="divide-y divide-white/5">
              <li
                v-for="(rule, idx) in artistGenreRules"
                :key="idx"
                class="flex items-center gap-3 px-4 py-2.5 hover:bg-white/3 transition-colors"
              >
                <span
                  class="flex-1 text-sm font-mono text-base-content/80 truncate"
                >
                  *{{ rule.pattern }}*
                </span>
                <Icon
                  icon="clarity:arrow-line"
                  class="h-3.5 w-3.5 text-base-content/30 shrink-0"
                />
                <span class="text-sm font-medium text-primary truncate flex-1">
                  {{ rule.genre }}
                </span>
                <button
                  class="icon-btn h-7 w-7 text-error/50 hover:text-error hover:bg-error/10 shrink-0"
                  @click="removeArtistGenreRule(idx)"
                  title="Remove rule"
                >
                  <Icon icon="clarity:times-line" class="h-3.5 w-3.5" />
                </button>
              </li>
            </ul>
          </div>
        </section>

        </div><!-- end TAB 2: ARTIST SETTINGS -->

        <!-- ══════════════════════════════════════════════════════════ -->
        <!-- TAB 1: GENRE RULES                                        -->
        <!-- ══════════════════════════════════════════════════════════ -->
        <div v-show="activeTab === 'genre'">

        <!-- ══════════════════════════════════════════════════════════ -->
        <!-- GENRE RULES                                               -->
        <!-- ══════════════════════════════════════════════════════════ -->
        <section class="mb-10">
          <div class="flex items-center justify-between mb-3">
            <div>
              <h2 class="text-base font-semibold">
                {{ t('organizer.genreRules') }}
              </h2>
              <p class="text-xs text-base-content/50 mt-0.5">
                {{ t('organizer.genreRulesHint') }}
              </p>
            </div>
            <span class="text-xs text-base-content/40">
              {{ t('organizer.ruleCount', { n: filteredGenreRules.length }) }}
            </span>
          </div>

          <!-- Controls row -->
          <div class="flex flex-wrap gap-2 mb-3">
            <div class="relative flex-1 min-w-[200px]">
              <Icon
                icon="clarity:search-line"
                class="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-base-content/40 pointer-events-none"
              />
              <input
                v-model="genreSearch"
                type="text"
                :placeholder="t('organizer.filterRules')"
                class="w-full rounded-xl bg-base-100/85 border border-white/10 focus:border-primary/60 focus:outline-none pl-8 pr-3 py-2 text-sm"
              />
            </div>
            <select
              v-model="folderFilter"
              class="rounded-xl bg-base-100/85 border border-white/10 focus:border-primary/60 focus:outline-none px-3 py-2 text-sm"
            >
              <option value="">{{ t('organizer.filterFolder') }}</option>
              <option v-for="f in availableFolders" :key="f" :value="f">
                {{ f }}
              </option>
            </select>
          </div>

          <!-- Add new rule form -->
          <div
            class="surface rounded-2xl p-3 mb-3 flex flex-wrap gap-2 items-center"
          >
            <input
              v-model="newKeyword"
              type="text"
              :placeholder="t('organizer.newKeyword')"
              class="flex-1 min-w-[140px] rounded-xl bg-base-100/85 border border-white/10 focus:border-primary/60 focus:outline-none px-3 py-2 text-sm"
              @keydown.enter="addGenreRule"
            />
            <Icon
              icon="clarity:arrow-line"
              class="h-4 w-4 text-base-content/30 shrink-0"
            />
            <div class="flex-1 min-w-[140px] relative">
              <input
                v-model="newFolder"
                type="text"
                list="folder-list"
                :placeholder="t('organizer.newFolder')"
                class="w-full rounded-xl bg-base-100/85 border border-white/10 focus:border-primary/60 focus:outline-none px-3 py-2 text-sm"
                @keydown.enter="addGenreRule"
              />
              <datalist id="folder-list">
                <option v-for="f in availableFolders" :key="f" :value="f" />
              </datalist>
            </div>
            <button
              class="btn btn-sm h-10 px-4 rounded-xl border-white/10 bg-base-100/85 hover:bg-primary/10 hover:border-primary/50 hover:text-primary transition-colors"
              @click="addGenreRule"
            >
              <Icon icon="clarity:plus-line" class="h-4 w-4 mr-1" />
              {{ t('organizer.addRule') }}
            </button>
          </div>

          <!-- Rules list -->
          <div class="surface rounded-2xl overflow-hidden">
            <div
              v-if="paginatedGenreRules.length === 0"
              class="p-8 text-center text-sm text-base-content/40"
            >
              No rules match your filter.
            </div>
            <ul v-else class="divide-y divide-white/5">
              <li
                v-for="(rule, idx) in paginatedGenreRules"
                :key="getRuleKey(rule)"
                class="flex items-center gap-3 px-4 py-2.5 hover:bg-white/3 transition-colors"
              >
                <span
                  class="flex-1 text-sm font-mono text-base-content/80 truncate"
                >
                  {{ rule.keyword }}
                </span>
                <Icon
                  icon="clarity:arrow-line"
                  class="h-3.5 w-3.5 text-base-content/30 shrink-0"
                />
                <span
                  class="text-xs font-semibold px-2 py-0.5 rounded-lg shrink-0"
                  :class="folderBadgeClass(rule.folder)"
                >
                  {{ rule.folder }}
                </span>
                <button
                  class="icon-btn h-7 w-7 text-error/50 hover:text-error hover:bg-error/10 shrink-0"
                  @click="removeGenreRule(rule)"
                  title="Remove rule"
                >
                  <Icon icon="clarity:times-line" class="h-3.5 w-3.5" />
                </button>
              </li>
            </ul>
          </div>

          <!-- Genre pagination -->
          <div
            v-if="genreTotalPages > 1"
            class="mt-4 flex items-center justify-center gap-1"
          >
            <button
              class="icon-btn"
              :disabled="genrePage === 1"
              @click="genrePage--"
              :title="t('common.previousPage')"
            >
              <Icon icon="clarity:angle-line" class="h-4 w-4 rotate-[-90deg]" />
            </button>
            <span class="text-xs text-base-content/50 px-2">
              {{ genrePage }} / {{ genreTotalPages }}
            </span>
            <button
              class="icon-btn"
              :disabled="genrePage === genreTotalPages"
              @click="genrePage++"
              :title="t('common.nextPage')"
            >
              <Icon icon="clarity:angle-line" class="h-4 w-4 rotate-90" />
            </button>
          </div>
        </section>

        <!-- ══════════════════════════════════════════════════════════ -->
        <!-- ARTIST ALIAS RULES                                        -->
        <!-- ══════════════════════════════════════════════════════════ -->
        <section>
          <div class="mb-3">
            <h2 class="text-base font-semibold">
              {{ t('organizer.artistRules') }}
            </h2>
            <p class="text-xs text-base-content/50 mt-0.5">
              {{ t('organizer.artistRulesHint') }}
            </p>
          </div>

          <!-- Add alias form -->
          <div
            class="surface rounded-2xl p-3 mb-3 flex flex-wrap gap-2 items-center"
          >
            <input
              v-model="newPattern"
              type="text"
              :placeholder="t('organizer.newPattern')"
              class="flex-1 min-w-[140px] rounded-xl bg-base-100/85 border border-white/10 focus:border-primary/60 focus:outline-none px-3 py-2 text-sm"
              @keydown.enter="addArtistRule"
            />
            <Icon
              icon="clarity:arrow-line"
              class="h-4 w-4 text-base-content/30 shrink-0"
            />
            <input
              v-model="newArtist"
              type="text"
              :placeholder="t('organizer.newArtist')"
              class="flex-1 min-w-[140px] rounded-xl bg-base-100/85 border border-white/10 focus:border-primary/60 focus:outline-none px-3 py-2 text-sm"
              @keydown.enter="addArtistRule"
            />
            <button
              class="btn btn-sm h-10 px-4 rounded-xl border-white/10 bg-base-100/85 hover:bg-primary/10 hover:border-primary/50 hover:text-primary transition-colors"
              @click="addArtistRule"
            >
              <Icon icon="clarity:plus-line" class="h-4 w-4 mr-1" />
              {{ t('organizer.addAlias') }}
            </button>
          </div>

          <!-- Artist rules list -->
          <div class="surface rounded-2xl overflow-hidden">
            <div
              v-if="artistRules.length === 0"
              class="p-8 text-center text-sm text-base-content/40"
            >
              No artist alias rules yet. Add one above.
            </div>
            <ul v-else class="divide-y divide-white/5">
              <li
                v-for="(rule, idx) in artistRules"
                :key="idx"
                class="flex items-center gap-3 px-4 py-2.5 hover:bg-white/3 transition-colors"
              >
                <span
                  class="flex-1 text-sm font-mono text-base-content/80 truncate"
                >
                  *{{ rule.pattern }}*
                </span>
                <Icon
                  icon="clarity:arrow-line"
                  class="h-3.5 w-3.5 text-base-content/30 shrink-0"
                />
                <span class="text-sm font-medium text-primary truncate flex-1">
                  {{ rule.artist }}
                </span>
                <button
                  class="icon-btn h-7 w-7 text-error/50 hover:text-error hover:bg-error/10 shrink-0"
                  @click="removeArtistRule(idx)"
                  title="Remove alias"
                >
                  <Icon icon="clarity:times-line" class="h-3.5 w-3.5" />
                </button>
              </li>
            </ul>
          </div>
        </section>

        <!-- ── Separator Tokens ─────────────────────────────────────────── -->
        <section
          class="rounded-2xl border border-base-content/10 overflow-hidden"
        >
          <div
            class="px-5 py-4 border-b border-base-content/8 bg-base-content/2"
          >
            <h2 class="text-sm font-semibold">
              {{ t('organizer.separatorTokens') }}
            </h2>
            <p class="text-xs text-base-content/50 mt-0.5">
              {{ t('organizer.separatorTokensHint') }}
            </p>
          </div>
          <div class="px-5 py-4 space-y-3">
            <!-- Token chips -->
            <div class="flex flex-wrap gap-1.5">
              <span
                v-for="sep in separatorTokens"
                :key="sep"
                class="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full bg-base-content/8"
              >
                <span class="font-mono">{{ sep }}</span>
                <button
                  class="text-base-content/30 hover:text-error transition-colors ml-0.5"
                  @click="removeSeparator(sep)"
                >
                  <Icon icon="clarity:times-line" class="h-3 w-3" />
                </button>
              </span>
            </div>
            <!-- Add new separator -->
            <div class="flex gap-2">
              <input
                v-model="newSeparator"
                class="input input-sm h-9 flex-1 font-mono text-sm"
                :placeholder="t('organizer.newSeparator')"
                @keydown.enter.prevent="addSeparator"
              />
              <button
                class="btn btn-sm btn-ghost h-9 px-3"
                @click="addSeparator"
              >
                <Icon icon="clarity:plus-line" class="h-4 w-4" />
                {{ t('organizer.addSeparator') }}
              </button>
            </div>
          </div>
        </section>

        </div><!-- end TAB 1: GENRE RULES -->

        <!-- ── Cache Editor (Artist Settings tab) ──────────────────────────── -->
        <div v-show="activeTab === 'artist'">
        <!-- ── Cache Editor ──────────────────────────────────────────────── -->
        <section
          class="mt-8 rounded-2xl border border-base-content/10 overflow-hidden"
        >
          <div
            class="px-5 py-4 border-b border-base-content/8 bg-base-content/2 flex items-center justify-between gap-3"
          >
            <div>
              <h2 class="text-sm font-semibold">
                {{ t('organizer.cacheEditor') }}
              </h2>
              <p class="text-xs text-base-content/50 mt-0.5">
                {{ t('organizer.cacheEditorHint') }}
              </p>
            </div>
            <div class="flex items-center gap-2 shrink-0">
              <span class="text-xs text-base-content/40">{{
                t('organizer.cacheCount', { n: cacheTotal })
              }}</span>
              <button
                v-if="cacheTotal > 0"
                class="btn btn-xs btn-ghost text-error/60 hover:text-error h-8 px-3"
                @click="clearCache"
              >
                {{ t('organizer.cacheClearAll') }}
              </button>
            </div>
          </div>

          <!-- Search -->
          <div class="px-5 pt-3 pb-2">
            <input
              v-model="cacheSearch"
              class="input input-sm h-9 w-full text-sm"
              :placeholder="t('organizer.cacheSearch')"
            />
          </div>

          <!-- Status msg -->
          <Transition name="toast">
            <div v-if="cacheMsg" class="px-5 pb-2">
              <span class="text-xs text-success">{{ cacheMsg }}</span>
            </div>
          </Transition>

          <!-- Cache list -->
          <div v-if="cacheLoading" class="flex items-center justify-center p-8">
            <span class="loading loading-spinner loading-sm" />
          </div>
          <ul
            v-else-if="cacheItems.length"
            class="divide-y divide-base-content/5"
          >
            <li
              v-for="item in cacheItems"
              :key="item.artist_norm"
              class="flex items-start gap-3 px-5 py-3 hover:bg-base-content/3 group"
            >
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="text-sm font-medium">{{
                    item.artist_norm
                  }}</span>
                  <span
                    v-if="item.genre"
                    class="text-[10px] px-1.5 py-0.5 rounded-md bg-primary/15 text-primary font-medium"
                    >{{ item.genre }}</span
                  >
                  <span class="text-[10px] text-base-content/25">{{
                    new Date(item.learned_at * 1000).toLocaleDateString()
                  }}</span>
                </div>
                <div class="flex gap-1 mt-1.5 flex-wrap">
                  <span
                    v-for="album in item.albums"
                    :key="album"
                    class="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-md bg-base-content/8 text-base-content/60"
                  >
                    {{ album }}
                    <button
                      class="text-base-content/30 hover:text-error transition-colors ml-0.5"
                      @click.stop="removeAlbum(item, album)"
                    >
                      ×
                    </button>
                  </span>
                  <span
                    v-if="!item.albums?.length"
                    class="text-[10px] text-base-content/25 italic"
                    >{{ t('organizer.cacheAlbums') }}: —</span
                  >
                </div>
              </div>
              <button
                class="icon-btn h-7 w-7 text-error/40 hover:text-error hover:bg-error/10 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity mt-0.5"
                @click="deleteCacheEntry(item)"
              >
                <Icon icon="clarity:trash-line" class="h-3.5 w-3.5" />
              </button>
            </li>
          </ul>
          <div
            v-else
            class="px-5 py-6 text-center text-sm text-base-content/40"
          >
            {{
              cacheTotal === 0
                ? t('organizer.cacheCount', { n: 0 })
                : t('common.noResults')
            }}
          </div>

          <!-- Cache pagination -->
          <div
            v-if="cacheTotal > cachePageSize"
            class="px-5 py-3 flex items-center justify-between border-t border-base-content/8"
          >
            <button
              class="btn btn-xs btn-ghost"
              :disabled="cachePage === 1"
              @click="cachePrev"
            >
              ←
            </button>
            <span class="text-xs text-base-content/40"
              >{{ cachePage }} /
              {{ Math.ceil(cacheTotal / cachePageSize) }}</span
            >
            <button
              class="btn btn-xs btn-ghost"
              :disabled="cachePage >= Math.ceil(cacheTotal / cachePageSize)"
              @click="cacheNext"
            >
              →
            </button>
          </div>
        </section>
        </div><!-- end Cache Editor artist tab -->
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { Icon } from '@iconify/vue'
import Navbar from '/src/components/Navbar.vue'
import Settings from '/src/components/Settings.vue'
import API from '/src/model/api'
import { useI18n } from '/src/i18n'

const GENRE_PAGE_SIZE = 50

const { t } = useI18n()

const activeTab = ref('genre')
const loading = ref(true)
const saving = ref(false)
const saveResult = ref('')
const isDirty = ref(false)
const isSaved = ref(false)

const genreRules = ref([])
const artistRules = ref([])
const artistGenreRules = ref([])
const availableFolders = ref([])
const separatorTokens = ref([])
const newSeparator = ref('')

const soundcloudClientId = ref('')
const scDiscovering = ref(false)
const scMsg = ref('')
const scError = ref(false)

const genreSearch = ref('')
const folderFilter = ref('')
const genrePage = ref(1)

const newKeyword = ref('')
const newFolder = ref('')
const newPattern = ref('')
const newArtist = ref('')
const newArtistPattern = ref('')
const newArtistGenre = ref('')

const filteredGenreRules = computed(() => {
  let rules = genreRules.value
  if (genreSearch.value) {
    const q = genreSearch.value.toLowerCase()
    rules = rules.filter(
      (r) =>
        r.keyword.toLowerCase().includes(q) ||
        r.folder.toLowerCase().includes(q)
    )
  }
  if (folderFilter.value) {
    rules = rules.filter((r) => r.folder === folderFilter.value)
  }
  return rules
})

const genreTotalPages = computed(() =>
  Math.max(1, Math.ceil(filteredGenreRules.value.length / GENRE_PAGE_SIZE))
)

const paginatedGenreRules = computed(() => {
  const start = (genrePage.value - 1) * GENRE_PAGE_SIZE
  return filteredGenreRules.value.slice(start, start + GENRE_PAGE_SIZE)
})

watch([genreSearch, folderFilter], () => {
  genrePage.value = 1
})

watch(
  [genreRules, artistRules, artistGenreRules],
  () => {
    isDirty.value = true
    isSaved.value = false
  },
  { deep: true }
)

function getRuleKey(rule) {
  return `${rule.keyword}::${rule.folder}`
}

const folderColorMap = {}
const folderColors = [
  'bg-primary/10 text-primary',
  'bg-secondary/10 text-secondary',
  'bg-accent/10 text-accent',
  'bg-warning/10 text-warning',
  'bg-success/10 text-success',
  'bg-error/10 text-error',
  'bg-info/10 text-info',
]
let colorIdx = 0
function folderBadgeClass(folder) {
  if (!folderColorMap[folder]) {
    folderColorMap[folder] = folderColors[colorIdx % folderColors.length]
    colorIdx++
  }
  return folderColorMap[folder]
}

function addGenreRule() {
  const fl = newFolder.value.trim()
  if (!fl) return
  const keywords = newKeyword.value
    .split(',')
    .map((k) => k.trim().toLowerCase())
    .filter(Boolean)
  if (!keywords.length) return
  const newRules = keywords
    .filter((kw) => !genreRules.value.some((r) => r.keyword === kw))
    .map((kw) => ({ keyword: kw, folder: fl }))
  if (!newRules.length) return
  genreRules.value = [...newRules, ...genreRules.value]
  if (!availableFolders.value.includes(fl)) {
    availableFolders.value = [...availableFolders.value, fl].sort()
  }
  newKeyword.value = ''
  newFolder.value = ''
  genrePage.value = 1
}

function addArtistGenreRule() {
  const pat = newArtistPattern.value.trim()
  const genre = newArtistGenre.value.trim()
  if (!pat || !genre) return
  artistGenreRules.value = [...artistGenreRules.value, { pattern: pat, genre }]
  newArtistPattern.value = ''
  newArtistGenre.value = ''
}

function removeArtistGenreRule(idx) {
  artistGenreRules.value = artistGenreRules.value.filter((_, i) => i !== idx)
}

function removeGenreRule(rule) {
  genreRules.value = genreRules.value.filter(
    (r) => !(r.keyword === rule.keyword && r.folder === rule.folder)
  )
}

function addArtistRule() {
  const pat = newPattern.value.trim()
  const art = newArtist.value.trim()
  if (!pat || !art) return
  artistRules.value = [...artistRules.value, { pattern: pat, artist: art }]
  newPattern.value = ''
  newArtist.value = ''
}

function removeArtistRule(idx) {
  artistRules.value = artistRules.value.filter((_, i) => i !== idx)
}

function addSeparator() {
  const s = newSeparator.value.trim()
  if (s && !separatorTokens.value.includes(s)) {
    separatorTokens.value = [...separatorTokens.value, s]
    isDirty.value = true
  }
  newSeparator.value = ''
}

function removeSeparator(sep) {
  separatorTokens.value = separatorTokens.value.filter((s) => s !== sep)
  isDirty.value = true
}

// ── Cache Editor ──────────────────────────────────────────────────────────────

const cacheItems = ref([])
const cacheTotal = ref(0)
const cacheSearch = ref('')
const cachePage = ref(1)
const cachePageSize = 20
const cacheLoading = ref(false)
const cacheMsg = ref('')

async function loadCache() {
  cacheLoading.value = true
  try {
    const offset = (cachePage.value - 1) * cachePageSize
    const res = await API.listCacheTracks(
      cacheSearch.value,
      cachePageSize,
      offset
    )
    cacheItems.value = res.data.items || []
    cacheTotal.value = res.data.total || 0
  } catch (e) {
    console.error('Cache load failed', e)
  } finally {
    cacheLoading.value = false
  }
}

async function deleteCacheEntry(item) {
  try {
    await API.deleteCacheTrack(item.artist_norm)
    cacheMsg.value = t('organizer.cacheDeleted')
    loadCache()
  } catch {}
  setTimeout(() => {
    cacheMsg.value = ''
  }, 3000)
}

async function removeAlbum(item, album) {
  try {
    await API.deleteArtistAlbum(item.artist_norm, album)
    item.albums = item.albums.filter((a) => a !== album)
    cacheMsg.value = t('organizer.cacheDeleted')
  } catch {}
  setTimeout(() => {
    cacheMsg.value = ''
  }, 3000)
}

function cachePrev() {
  cachePage.value--
  loadCache()
}

function cacheNext() {
  cachePage.value++
  loadCache()
}

async function clearCache() {
  if (!confirm(t('organizer.cacheClearConfirm', { n: cacheTotal.value })))
    return
  try {
    await API.clearAllCache()
    cacheMsg.value = t('organizer.cacheClearedAll')
    loadCache()
  } catch {}
  setTimeout(() => {
    cacheMsg.value = ''
  }, 3000)
}

let cacheSearchTimeout = null
watch(cacheSearch, () => {
  clearTimeout(cacheSearchTimeout)
  cacheSearchTimeout = setTimeout(() => {
    cachePage.value = 1
    loadCache()
  }, 300)
})

async function loadConfig() {
  loading.value = true
  try {
    const res = await API.getOrganizerConfig()
    genreRules.value = res.data.genre_rules || []
    artistRules.value = res.data.artist_rules || []
    artistGenreRules.value = res.data.artist_genre_rules || []
    availableFolders.value = res.data.available_folders || []
    separatorTokens.value = res.data.artist_separator_tokens || []
    soundcloudClientId.value = res.data.soundcloud_client_id || ''
    isDirty.value = false
  } catch (e) {
    console.error('Failed to load organizer config', e)
  } finally {
    loading.value = false
  }
}

async function saveRules() {
  saving.value = true
  saveResult.value = ''
  try {
    await API.saveOrganizerConfig({
      genre_rules: genreRules.value,
      artist_rules: artistRules.value,
      artist_genre_rules: artistGenreRules.value,
      artist_separator_tokens: separatorTokens.value,
      soundcloud_client_id: soundcloudClientId.value,
    })
    saveResult.value = 'ok'
    isDirty.value = false
    isSaved.value = true
    setTimeout(() => {
      saveResult.value = ''
    }, 4000)
  } catch {
    saveResult.value = 'error'
    setTimeout(() => {
      saveResult.value = ''
    }, 4000)
  } finally {
    saving.value = false
  }
}

async function discoverSoundcloudId() {
  scDiscovering.value = true
  scMsg.value = ''
  scError.value = false
  try {
    const res = await API.discoverSoundcloudClientId()
    soundcloudClientId.value = res.data.client_id
    scMsg.value = t('organizer.soundcloudFound')
  } catch {
    scError.value = true
    scMsg.value = t('organizer.soundcloudNotFound')
  } finally {
    scDiscovering.value = false
  }
}

onMounted(() => {
  loadConfig()
  loadCache()
})
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
.status-enter-active,
.status-leave-active {
  transition: opacity 0.2s;
}
.status-enter-from,
.status-leave-to {
  opacity: 0;
}
</style>
