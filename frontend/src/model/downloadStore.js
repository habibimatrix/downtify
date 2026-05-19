import { ref, computed } from 'vue'

export const activeDownloadCount = ref(0)
export const activeOrganizerCount = ref(0)
export const processingCount = computed(
  () => activeDownloadCount.value + activeOrganizerCount.value
)
