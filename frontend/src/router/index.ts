import { createRouter, createWebHistory } from 'vue-router'
import Login from '@/views/Login.vue'
import Register from '@/views/Register.vue'
import Forgot from '@/views/Forgot.vue'
import Home from '@/views/Home.vue'
import Practice from '@/views/Practice.vue'
import Bank from '@/views/Bank.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/login' },
    { path: '/login', component: Login },
    { path: '/register', component: Register },
    { path: '/forgot', component: Forgot },
    { path: '/home', component: Home },
    { path: '/banks/:id', component: Bank },
    { path: '/practice', component: Practice },
  ],
})

router.beforeEach((to) => {
  const token = localStorage.getItem('token')
  const whiteList = ['/login', '/register', '/forgot']
  if (!whiteList.includes(to.path) && !token) return '/login'
})

export default router
