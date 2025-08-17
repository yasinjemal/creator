<template>
  <div>
    <h1>CreatorFlow</h1>
    <form @submit.prevent="createBrand">
      <label>Name: <input v-model="name" /></label>
      <button type="submit">Create Brand</button>
    </form>
    <pre v-if="brand">{{ brand }}</pre>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import axios from 'axios'

const name = ref('')
const brand = ref(null)

async function createBrand() {
  const res = await axios.post('/api/brand', { name: name.value })
  brand.value = res.data
}
</script>
