<template>
  <div
    v-if="show"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    @click.self="$emit('close')"
  >
    <div class="bg-base-100 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col">
      <!-- Header -->
      <div class="flex items-center justify-between p-4 border-b border-base-content/10">
        <div>
          <h2 class="text-base font-semibold">{{ t('audit.title') }}</h2>
          <p class="text-xs text-base-content/50 mt-0.5 truncate max-w-sm">{{ trackName }}</p>
        </div>
        <button class="icon-btn" @click="$emit('close')">
          <Icon icon="clarity:close-line" class="h-5 w-5" />
        </button>
      </div>

      <!-- Loading -->
      <div v-if="loading" class="flex-1 flex items-center justify-center p-8">
        <span class="loading loading-spinner loading-md" />
      </div>

      <!-- Error -->
      <div v-else-if="error" class="flex-1 flex items-center justify-center p-8">
        <p class="text-sm text-base-content/50">{{ error }}</p>
      </div>

      <!-- Steps -->
      <div v-else-if="audit" class="flex-1 overflow-y-auto p-4 space-y-2">
        <!-- Spotify-ID banner -->
        <div v-if="audit.cache?.spotify_sourced" class="flex items-center gap-2 rounded-xl bg-info/10 border border-info/20 px-3 py-2 mb-1">
          <Icon icon="clarity:bolt-line" class="h-3.5 w-3.5 text-info shrink-0" />
          <span class="text-[11px] text-info">Spotify-Download: Artist / Album / Title direkt übernommen · Schritte 1–9 übersprungen</span>
        </div>
        <div
          v-for="step in audit.steps"
          :key="step.step ?? step.name"
          class="rounded-xl border border-base-content/8 overflow-hidden"
        >
          <!-- Step header -->
          <button
            class="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-base-content/4 transition-colors text-left"
            @click="toggleStep(step.step ?? step.name)"
          >
            <!-- Step badge -->
            <span
              class="text-[10px] font-bold px-2 py-0.5 rounded-full shrink-0"
              :class="stepBadgeClass(step)"
            >
              {{ stepLabel(step) }}
            </span>
            <span class="text-sm font-medium flex-1">{{ step.name }}</span>
            <!-- Summary chips -->
            <span
              v-if="step.step === 2 && step.ergebnis1"
              class="text-[10px] text-base-content/40 hidden sm:block truncate max-w-[200px]"
            >
              {{ qualitySummary(step.ergebnis1, step.status1) }}
            </span>
            <span
              v-if="step.step === 11 && step.rules_applied?.length"
              class="text-[10px] bg-warning/15 text-warning px-2 py-0.5 rounded-full shrink-0"
            >
              {{ step.rules_applied.length }} {{ t('audit.rulesApplied') }}
            </span>
            <span
              v-if="step.name === 'Cache-Hit'"
              class="text-[10px] bg-success/15 text-success px-2 py-0.5 rounded-full shrink-0"
            >
              {{ t('audit.cacheHit') }}
            </span>
            <Icon
              icon="clarity:angle-line"
              class="h-3.5 w-3.5 text-base-content/30 shrink-0 transition-transform"
              :class="expandedSteps.has(step.step ?? step.name) ? 'rotate-180' : ''"
            />
          </button>

          <!-- Step body -->
          <div
            v-if="expandedSteps.has(step.step ?? step.name)"
            class="px-3 pb-3 pt-1 border-t border-base-content/8 bg-base-content/2"
          >
            <!-- Step 0.5: Artist-Knowledge-Cache -->
            <div v-if="step.step === '0.5'" class="space-y-2">
              <div v-if="step.action?.includes('vollständiger Skip')" class="flex items-center gap-1.5">
                <Icon icon="clarity:bolt-line" class="h-3.5 w-3.5 text-warning" />
                <span class="text-[11px] text-warning font-medium">{{ t('audit.cacheSkipped') }}</span>
              </div>
              <div v-if="step.hit" class="space-y-1">
                <div class="flex items-center gap-1.5 text-[11px]">
                  <Icon icon="clarity:storage-line" class="h-3.5 w-3.5 text-primary" />
                  <span class="text-base-content/40 w-12 shrink-0">Genre</span>
                  <span class="text-primary font-medium">{{ step.genre || '—' }}</span>
                </div>
                <div v-if="step.albums?.length" class="flex items-start gap-1.5 text-[11px]">
                  <span class="text-base-content/40 w-12 shrink-0 mt-0.5">Alben</span>
                  <span class="text-base-content/60 flex-1">{{ step.albums.join(', ') }}</span>
                </div>
              </div>
              <p v-else class="text-[11px] text-base-content/40 flex items-center gap-1.5">
                <Icon icon="clarity:search-line" class="h-3.5 w-3.5" />
                Artist nicht bekannt — vollständiges Voting läuft
              </p>
            </div>

            <!-- Step 0: Tag values -->
            <div v-else-if="step.step === 0 && step.values" class="grid grid-cols-2 gap-1.5">
              <div v-for="(val, key) in step.values" :key="key" class="flex items-center gap-1.5 text-[11px]">
                <span class="text-base-content/40 capitalize w-12 shrink-0">{{ key }}</span>
                <span class="text-base-content/70 font-medium truncate">{{ val || '—' }}</span>
              </div>
            </div>

            <!-- Step 1: Source matrix -->
            <div v-else-if="step.step === 1 && step.sources" class="overflow-x-auto">
              <table class="w-full text-[11px]">
                <thead>
                  <tr class="text-base-content/40">
                    <th class="text-left py-1 pr-3 font-medium">{{ t('audit.source') }}</th>
                    <th class="text-left py-1 px-2 font-medium">{{ t('audit.genre') }}</th>
                    <th class="text-left py-1 px-2 font-medium">{{ t('audit.artist') }}</th>
                    <th class="text-left py-1 px-2 font-medium">{{ t('audit.album') }}</th>
                    <th class="text-left py-1 px-2 font-medium">{{ t('audit.title') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(meta, src) in step.sources" :key="src" class="border-t border-base-content/5">
                    <td class="py-1 pr-3 font-medium text-base-content/60 capitalize">{{ src }}</td>
                    <td class="py-1 px-2 text-base-content/70">{{ meta.genre || '—' }}</td>
                    <td class="py-1 px-2 text-base-content/70">{{ meta.artist || '—' }}</td>
                    <td class="py-1 px-2 text-base-content/70 italic">{{ meta.album || '—' }}</td>
                    <td class="py-1 px-2 text-base-content/70">{{ meta.title || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- Step 2: Voting results -->
            <div v-else-if="step.step === 2" class="space-y-2">
              <div v-for="(count, field) in step.counts" :key="field" class="flex items-center gap-2">
                <span class="text-[10px] text-base-content/40 w-12 shrink-0 capitalize">{{ field }}</span>
                <span class="text-xs font-medium text-base-content/80 flex-1">{{ count.winner || '—' }}</span>
                <span
                  class="text-[10px] px-2 py-0.5 rounded-full"
                  :class="qualityClass(field === 'genre' ? (count.has_clear ? 'sehr hoch' : 'niedrig') : count.quality)"
                >
                  {{ field === 'genre' ? (count.has_clear ? 'JA' : 'NEIN') : count.quality }}
                </span>
              </div>
            </div>

            <!-- Step 5/7: Written/Open fields -->
            <div v-else-if="(step.step === 5 || step.step === 7) && (step.written || step.open)" class="flex gap-3 flex-wrap">
              <div v-if="step.written?.length" class="flex items-center gap-1.5">
                <Icon icon="clarity:check-circle-line" class="h-3.5 w-3.5 text-success" />
                <span class="text-[11px] text-success">{{ step.written.join(', ') }}</span>
              </div>
              <div v-if="step.open?.length" class="flex items-center gap-1.5">
                <Icon icon="clarity:clock-line" class="h-3.5 w-3.5 text-warning" />
                <span class="text-[11px] text-warning">{{ step.open.join(', ') }}</span>
              </div>
            </div>

            <!-- Step 6: MB result + country -->
            <div v-else-if="step.step === 6" class="space-y-1">
              <div v-if="step.result && Object.values(step.result).some(Boolean)" class="grid grid-cols-2 gap-1.5">
                <div v-for="(val, key) in step.result" :key="key" class="flex items-center gap-1.5 text-[11px]">
                  <span class="text-base-content/40 capitalize w-12 shrink-0">{{ key }}</span>
                  <span class="text-base-content/70 font-medium truncate">{{ val || '—' }}</span>
                </div>
              </div>
              <div v-if="step.country" class="flex items-center gap-1.5 mt-1">
                <span class="text-[10px] text-base-content/40">Country:</span>
                <span class="text-[11px] font-medium">{{ step.country }}</span>
              </div>
            </div>

            <!-- Step 8/9: Fingerprint / Final -->
            <div v-else-if="(step.step === 8 || step.step === 9)" class="grid grid-cols-2 gap-1.5">
              <template v-for="(val, key) in (step.result || step.ergebnis4 || {})" :key="key">
                <div v-if="val" class="flex items-center gap-1.5 text-[11px]">
                  <span class="text-base-content/40 capitalize w-12 shrink-0">{{ key }}</span>
                  <span class="text-base-content/70 font-medium truncate">{{ val }}</span>
                </div>
              </template>
            </div>

            <!-- Step 10: org fields -->
            <div v-else-if="step.step === 10 && step.org" class="space-y-1.5">
              <div v-for="(meta, field) in step.org" :key="field" class="flex items-center gap-2">
                <span class="text-[10px] text-base-content/40 w-12 shrink-0 capitalize">{{ field }}</span>
                <span class="text-xs font-medium flex-1">{{ typeof meta === 'object' ? meta.value : meta }}</span>
                <span v-if="typeof meta === 'object' && meta.source" class="text-[10px] text-base-content/30 italic">{{ meta.source }}</span>
              </div>
              <div v-if="step.source" class="mt-1 text-[10px] text-base-content/40 italic">{{ step.source }}</div>
            </div>

            <!-- Step 11: Rules applied -->
            <div v-else-if="step.step === 11">
              <div v-if="step.rules_applied?.length" class="space-y-1">
                <div v-for="rule in step.rules_applied" :key="rule.field" class="flex items-center gap-2 text-xs">
                  <span class="text-base-content/40 capitalize">{{ rule.field }}:</span>
                  <span class="text-base-content/60 line-through">{{ rule.before }}</span>
                  <Icon icon="clarity:arrow-line" class="h-3 w-3 text-warning" />
                  <span class="text-warning font-medium">{{ rule.after }}</span>
                </div>
              </div>
              <p v-else class="text-[11px] text-base-content/40">{{ t('audit.noRulesApplied') }}</p>
            </div>

            <!-- Step 4.5: Album fuzzy match -->
            <div v-else-if="step.step === '4.5'" class="space-y-1">
              <p class="text-[11px] text-primary flex items-center gap-1.5">
                <Icon icon="clarity:storage-line" class="h-3.5 w-3.5" />
                {{ t('audit.cacheAlbumFuzzy') }}
              </p>
              <div class="flex items-center gap-2 text-[11px]">
                <span class="text-base-content/50 line-through">{{ step.original }}</span>
                <Icon icon="clarity:arrow-line" class="h-3 w-3 text-primary" />
                <span class="text-primary font-medium">{{ step.matched }}</span>
                <span class="text-base-content/30">({{ Math.round((step.score || 0) * 100) }}%)</span>
              </div>
            </div>

            <!-- Step 12: Artist-Cache write -->
            <div v-else-if="step.step === 12" class="space-y-1.5">
              <div v-if="step.genre_overwritten" class="flex items-center gap-1.5 text-[11px]">
                <Icon icon="clarity:warning-line" class="h-3.5 w-3.5 text-warning" />
                <span class="text-warning">{{ t('audit.cacheGenreOverwritten') }}:</span>
                <span class="text-base-content/50 line-through">{{ step.genre_prev }}</span>
                <Icon icon="clarity:arrow-line" class="h-3 w-3 text-warning" />
                <span class="text-warning font-medium">{{ step.genre }}</span>
              </div>
              <div v-if="step.album_new" class="flex items-center gap-1.5 text-[11px]">
                <Icon icon="clarity:plus-circle-line" class="h-3.5 w-3.5 text-success" />
                <span class="text-success">{{ t('audit.cacheAlbumLearned') }}:</span>
                <span class="font-medium">{{ step.album }}</span>
              </div>
              <div v-if="!step.genre_overwritten && !step.album_new" class="flex items-center gap-1.5 text-[11px]">
                <Icon icon="clarity:check-circle-line" class="h-3.5 w-3.5 text-success" />
                <span class="text-success">{{ t('audit.cacheWritten') }}</span>
              </div>
            </div>

            <!-- Cache step (legacy) -->
            <div v-else-if="step.name === 'Cache' || step.name === 'Cache-Hit'" class="flex items-center gap-2">
              <Icon icon="clarity:storage-line" class="h-4 w-4" :class="step.action === 'hit' ? 'text-success' : 'text-primary'" />
              <span class="text-xs">{{ step.action === 'hit' ? t('audit.cacheHit') : t('audit.cacheWritten') }}</span>
              <span v-if="step.key" class="text-[10px] text-base-content/40 font-mono">{{ step.key }}</span>
            </div>

            <!-- Generic fallback -->
            <pre v-else class="text-[10px] text-base-content/50 whitespace-pre-wrap">{{ JSON.stringify(step, null, 2) }}</pre>
          </div>
        </div>

        <!-- Cache footer -->
        <div v-if="audit.cache" class="rounded-xl border border-base-content/8 px-3 py-2.5 flex items-center gap-3">
          <Icon
            icon="clarity:storage-line"
            class="h-4 w-4 shrink-0"
            :class="audit.cache.action?.includes('hit') ? 'text-primary' : 'text-success'"
          />
          <span class="text-xs flex-1">
            <span class="font-medium">{{ t('audit.cache') }}:</span>
            {{ audit.cache.action?.includes('hit') ? t('audit.cacheHit') : t('audit.cacheWritten') }}
            <span v-if="audit.cache.spotify_sourced" class="text-info ml-1">· Spotify-ID</span>
          </span>
        </div>
      </div>

      <!-- No audit -->
      <div v-else class="flex-1 flex flex-col items-center justify-center p-8 gap-2">
        <Icon icon="clarity:info-circle-line" class="h-8 w-8 text-base-content/20" />
        <p class="text-sm text-base-content/50">{{ t('audit.noData') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { Icon } from '@iconify/vue'
import { useI18n } from '/src/i18n'
import API from '/src/model/api'

const { t } = useI18n()

const props = defineProps({
  show: Boolean,
  trackId: String,
  trackName: String,
})
defineEmits(['close'])

const loading = ref(false)
const error = ref('')
const audit = ref(null)
const expandedSteps = ref(new Set())

watch(
  () => props.show,
  async (val) => {
    if (!val) {
      audit.value = null
      error.value = ''
      expandedSteps.value = new Set()
      return
    }
    loading.value = true
    error.value = ''
    try {
      const res = await API.getAudit(props.trackId)
      audit.value = res.data
      // Auto-expand key steps
      const hasArtistCache = res.data.steps?.some((s) => s.step === '0.5' && s.hit)
      const hasFullSkip = res.data.cache?.spotify_sourced
      const autoExpand = hasFullSkip ? ['0.5', 12] : hasArtistCache ? ['0.5', 11, 12] : [0, 1, 2, 11]
      expandedSteps.value = new Set(autoExpand)
    } catch {
      error.value = t('audit.noData')
    } finally {
      loading.value = false
    }
  }
)

function toggleStep(key) {
  const s = new Set(expandedSteps.value)
  if (s.has(key)) s.delete(key)
  else s.add(key)
  expandedSteps.value = s
}

function stepLabel(step) {
  if (step.step === null || step.step === undefined) return '★'
  return `${step.step}`
}

function stepBadgeClass(step) {
  if (step.step === '0.5') return step.hit ? 'bg-primary/15 text-primary' : 'bg-base-content/10 text-base-content/40'
  if (step.step === '4.5') return 'bg-primary/15 text-primary'
  if (step.step === 12) return step.genre_overwritten ? 'bg-warning/15 text-warning' : 'bg-success/15 text-success'
  if (step.name === 'Cache-Hit') return 'bg-success/15 text-success'
  if (step.name === 'Cache') return 'bg-primary/15 text-primary'
  if (step.step === 11) return 'bg-warning/15 text-warning'
  if (step.step === 0) return 'bg-base-content/10 text-base-content/50'
  return 'bg-primary/10 text-primary'
}

function qualityClass(q) {
  if (q === 'sehr hoch' || q === 'JA') return 'bg-success/15 text-success'
  if (q === 'hoch') return 'bg-success/10 text-success/70'
  if (q === 'mittel') return 'bg-warning/15 text-warning'
  return 'bg-error/10 text-error/70'
}

function qualitySummary(ergebnis1, status1) {
  if (!ergebnis1 || !status1) return ''
  const done = Object.entries(status1).filter(([, v]) => v === 'abgeschlossen').map(([k]) => k)
  const open = Object.entries(status1).filter(([, v]) => v === 'offen').map(([k]) => k)
  const parts = []
  if (done.length) parts.push(`✓ ${done.join(', ')}`)
  if (open.length) parts.push(`⟳ ${open.join(', ')}`)
  return parts.join(' | ')
}
</script>

