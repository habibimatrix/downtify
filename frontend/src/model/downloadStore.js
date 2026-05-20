import { ref, computed } from 'vue'

// Module-level Sets survive component mount/unmount cycles so the badge
// stays correct regardless of which page the user is on.
const _activeDownloadIds = new Set()
const _activeOrganizerIds = new Set()

export const activeDownloadCount = ref(0)
export const activeOrganizerCount = ref(0)
export const processingCount = computed(
  () => activeDownloadCount.value + activeOrganizerCount.value
)

export function updateFromWs(msg) {
  const msgType = msg.type || ''

  if (msgType === 'organizer') {
    const id = msg.track_id || msg.song_name || '_'
    _activeOrganizerIds.add(id)
    activeOrganizerCount.value = _activeOrganizerIds.size
    return
  }
  if (msgType === 'organizer_done') {
    const id = msg.track_id || msg.song_name || '_'
    _activeOrganizerIds.delete(id)
    activeOrganizerCount.value = _activeOrganizerIds.size
    return
  }

  const status = msg.status
  if (!status) return
  const song = msg.song || {}
  const songId = song.song_id || song.url || JSON.stringify(song)
  if (!songId) return

  if (status === 'downloading') {
    _activeDownloadIds.add(songId)
  } else if (status === 'done' || status === 'error') {
    _activeDownloadIds.delete(songId)
  }
  activeDownloadCount.value = _activeDownloadIds.size
}
