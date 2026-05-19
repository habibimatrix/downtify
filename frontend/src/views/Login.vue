<template>
  <div class="min-h-screen flex items-center justify-center bg-base-200 p-4">
    <div class="w-full max-w-sm">
      <!-- Logo + Title -->
      <div class="text-center mb-8">
        <div class="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/15 mb-4">
          <Icon icon="clarity:music-note-line" class="h-8 w-8 text-primary" />
        </div>
        <h1 class="text-2xl font-bold tracking-tight">Downtiplx</h1>
        <p class="text-sm text-base-content/50 mt-1">Enter password to continue</p>
      </div>

      <!-- Login Card -->
      <form
        class="surface rounded-2xl p-6 space-y-4"
        @submit.prevent="submit"
      >
        <div>
          <input
            v-model="password"
            type="password"
            class="input w-full h-11 text-sm"
            :class="error ? 'border-error focus:border-error' : ''"
            placeholder="Password"
            autofocus
            autocomplete="current-password"
          />
          <Transition name="toast">
            <p v-if="error" class="text-xs text-error mt-1.5 flex items-center gap-1">
              <Icon icon="clarity:exclamation-circle-line" class="h-3.5 w-3.5 shrink-0" />
              Wrong password
            </p>
          </Transition>
        </div>

        <button
          type="submit"
          class="btn btn-primary w-full h-11 rounded-full"
          :disabled="loading || !password"
        >
          <span v-if="loading" class="loading loading-spinner loading-xs mr-2" />
          Sign in
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Icon } from '@iconify/vue'
import API from '/src/model/api'

const router = useRouter()
const route = useRoute()

const password = ref('')
const loading = ref(false)
const error = ref(false)

async function submit() {
  if (!password.value) return
  loading.value = true
  error.value = false
  try {
    await API.authLogin(password.value)
    const redirect = route.query.redirect || '/'
    router.replace(redirect)
  } catch {
    error.value = true
    password.value = ''
  } finally {
    loading.value = false
  }
}
</script>
