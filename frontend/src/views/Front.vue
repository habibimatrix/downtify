<template>
  <div>
    <Hero />
  </div>
</template>

<script>
import { onMounted } from 'vue'
import Hero from '/src/components/Hero.vue'

export default {
  components: { Hero },
  setup() {
    onMounted(() => {
      window.scroll(0, 0)
    })
    return {}
  },
}
</script>

<style scoped></style>
