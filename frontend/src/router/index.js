import { createWebHistory, createRouter } from 'vue-router'
import Home from '/src/views/Front.vue'
import Search from '/src/views/Search.vue'
import List from '/src/views/Downloads.vue'
import Monitor from '/src/views/Monitor.vue'
import Organizer from '/src/views/Organizer.vue'
import Login from '/src/views/Login.vue'
import API from '/src/model/api'
import config from '/src/config'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: Login,
    meta: { public: true },
  },
  {
    path: '/',
    name: 'Home',
    component: Home,
  },
  {
    path: '/search/:query',
    name: 'Search',
    component: Search,
  },
  {
    path: '/list',
    name: 'List',
    component: List,
  },
  {
    path: '/monitor',
    name: 'Monitor',
    component: Monitor,
  },
  {
    path: '/organizer',
    name: 'Organizer',
    component: Organizer,
  },
]

const router = createRouter({
  history: createWebHistory(config.BASEURL),
  routes,
})

router.beforeEach(async (to) => {
  if (to.meta.public) return true
  try {
    const res = await API.authStatus()
    const { protected: isProtected, authenticated } = res.data
    if (isProtected && !authenticated) {
      return { name: 'Login', query: { redirect: to.fullPath } }
    }
  } catch {
    // backend not reachable yet — allow through
  }
  return true
})

export default router
