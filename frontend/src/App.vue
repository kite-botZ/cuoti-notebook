<template>
  <router-view />
  <ToastContainer />
</template>

<script setup lang="ts">
import ToastContainer from '@/components/ToastContainer.vue'
</script>

<style>
:root {
  font-family: "PingFang SC", "Microsoft YaHei", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #18231f;
  background: #f5f7f6;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
}

* { box-sizing: border-box; }

html, body, #app { min-width: 320px; min-height: 100%; margin: 0; }

body { min-height: 100vh; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }

button, input, select, textarea { font: inherit; }
button { cursor: pointer; }
</style>