<template>
  <div>
    <h2>Generate Content</h2>
    <label>Brand ID: <input v-model="brandId" /></label>
    <label>Platform:
      <select v-model="platform">
        <option>instagram</option>
        <option>twitter</option>
        <option>youtube</option>
        <option>tiktok</option>
        <option>linkedin</option>
      </select>
    </label>
  <button @click="generate">Generate</button>
  <button v-if="draft" @click="schedule">Schedule Now</button>
  <button
    v-if="draft"
    @click="publish"
    class="publish-btn"
    :class="{ 'disabled-button': (uploadProgress > 0 && uploadProgress < 100) || !selectedFile }"
    style="margin-left:0.5rem"
    :disabled="(uploadProgress > 0 && uploadProgress < 100) || !selectedFile"
    :title="((uploadProgress > 0 && uploadProgress < 100) || !selectedFile) ? 'Select a file and wait for uploads to finish' : 'Publish now'"
  >
    Publish Now
  </button>
  <button v-if="uploadProgress > 0 && uploadProgress < 100" @click="cancelUpload" style="margin-left:0.5rem">Cancel Upload</button>

  <!-- Demo YouTube connect UI -->
  <div v-if="platform === 'youtube'" style="margin-top:1rem; padding:0.5rem; border:1px solid #eee">
    <h3>YouTube Connect (Demo)</h3>
    <button @click="startAuthorize">Connect YouTube</button>
    <button @click="checkConnection" style="margin-left:0.5rem">Check Connection</button>
    <div v-if="authUrl" style="margin-top:0.5rem">
      Authorize URL: <a :href="authUrl" target="_blank" rel="noopener">Open in new tab</a>
    </div>
    <div style="margin-top:0.5rem">
      <label>Paste code from redirect here: <input v-model="authCode" style="width:60%" /></label>
      <button @click="exchangeCode" style="margin-left:0.5rem">Exchange code</button>
    </div>
    <div v-if="status" style="margin-top:0.5rem"><strong>Status:</strong> {{ status }}</div>
    <pre v-if="tokenResponse" style="background:#f8f8f8; padding:0.5rem; margin-top:0.5rem">{{ tokenResponse }}</pre>
    <div v-if="maskedStatus" style="margin-top:0.5rem"><strong>Connection:</strong>
      <div>Connected: {{ maskedStatus.connected }}</div>
      <div v-if="maskedStatus.expires_in !== undefined">Expires in: {{ maskedStatus.expires_in }}s</div>
      <pre v-if="maskedStatus.token" style="background:#fff; padding:0.5rem; margin-top:0.25rem">{{ JSON.stringify(maskedStatus.token, null, 2) }}</pre>
    </div>
  </div>

  <div v-if="jobId">Scheduled Job ID: {{ jobId }}</div>
  <div v-if="publishJobId">Publish Job ID: {{ publishJobId }}</div>
  <div v-if="publishResult" style="margin-top:0.5rem"><strong>Publish Result:</strong>
    <pre style="background:#f8f8f8; padding:0.5rem">{{ publishResult }}</pre>
    <div v-if="publishResult && publishResult.toLowerCase().includes('error')" style="margin-top:0.5rem">
      <button @click="publish">Retry</button>
    </div>
  </div>
  <div v-if="toast" :style="{ position: 'fixed', right: '1rem', bottom: '1rem', background: toastType === 'error' ? '#fee2e2' : '#ecfdf5', padding: '0.5rem 0.75rem', borderRadius: '6px' }">{{ toast }}</div>
  <div v-if="uploadProgress > 0" style="margin-top:0.5rem">
    <strong>Upload progress:</strong>
    <div aria-live="polite">
    <div style="width:100%; background:#eee; height:12px; border-radius:6px; overflow:hidden; margin-top:0.25rem">
      <div :style="{ width: uploadProgress + '%', background: '#3b82f6', height: '100%' }"></div>
    </div>
    <div style="font-size:0.85rem; margin-top:0.25rem">{{ uploadProgress }}%</div>
    </div>
  </div>
  <div v-if="draft">
    <label>Video file (required): <input ref="fileInput" type="file" @change="onFileChange" /></label>
    <div v-if="selectedFile" style="margin-top:0.5rem; font-size:0.9rem; background:#fafafa; padding:0.5rem; border-radius:6px">
      <div><strong>Name:</strong> {{ selectedFile.name }}</div>
      <div><strong>Size:</strong> {{ (selectedFile.size / (1024*1024)).toFixed(2) }} MB</div>
      <div v-if="selectedFile.type"><strong>Type:</strong> {{ selectedFile.type }}</div>
    </div>
  </div>
  <div v-if="draftsList.length" style="margin-top:1rem">
    <h3>Drafts</h3>
    <ul>
      <li v-for="d in draftsList" :key="d._id" style="margin-bottom:0.5rem; padding:0.25rem; border:1px solid #eee">
        <div><strong>ID:</strong> {{ d._id }} — <strong>Platform:</strong> {{ d.platform }}</div>
        <div><strong>Payload:</strong> <pre style="display:inline">{{ JSON.stringify(d.payload, null, 2) }}</pre></div>
        <div v-if="d.status"><strong>Publish status:</strong> {{ d.status }}</div>
        <div v-if="d.publish_meta"><strong>Publish meta:</strong>
          <pre style="background:#fff; padding:0.25rem">{{ JSON.stringify(d.publish_meta, null, 2) }}</pre>
        </div>
      </li>
    </ul>
  </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import axios from 'axios'

const brandId = ref('')
const platform = ref('instagram')
const draft = ref(null)
const jobId = ref('')
const authUrl = ref('')
const status = ref('')
const authCode = ref('')
const tokenResponse = ref(null)
const maskedStatus = ref(null)
const publishJobId = ref('')
const publishResult = ref(null)
const selectedFile = ref(null)
const uploadProgress = ref(0)
let currentUpload = { xhr: null, canceled: false }
const uploadCompleted = ref(false)
const fileInput = ref(null)
const draftsList = ref([])
let statusInterval = null
const toast = ref('')
const toastType = ref('')

function showToast(msg, type = 'info', ms = 4000) {
  toast.value = msg
  toastType.value = type
  setTimeout(() => { toast.value = ''; toastType.value = '' }, ms)
}

function validateFile(file) {
  if (!file) return { ok: false, code: 'no_file', message: 'No file selected' }
  const MAX_UPLOAD_MB = parseInt(import.meta.env?.VITE_MAX_UPLOAD_MB || 512)
  const allowed = ['video/mp4', 'video/quicktime', 'video/webm', 'video/x-matroska']
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return { ok: false, code: 'payload_too_large', message: `File exceeds ${MAX_UPLOAD_MB}MB` }
  if (allowed.indexOf(file.type) === -1) return { ok: false, code: 'unsupported_media_type', message: 'Unsupported file type' }
  return { ok: true }
}

async function generate() {
  const res = await axios.post('/api/content/generate', { brand_id: brandId.value, platform: platform.value })
  draft.value = res.data
  // refresh drafts list to include the new draft
  await fetchDrafts()
}

async function schedule() {
  if (!draft.value) return
  const body = { draft_id: draft.value._id, post_time: new Date().toISOString() }
  const res = await axios.post('/api/content/schedule', body)
  jobId.value = res.data.job_id
  await fetchDrafts()
}

function onFileChange(e) {
  const f = e.target.files && e.target.files[0]
  const file = f || null
  const v = validateFile(file)
  if (!v.ok) {
    showToast(v.message, 'error')
    // clear input
    try { e.target.value = '' } catch (e) {}
    selectedFile.value = null
    return
  }
  selectedFile.value = file
  uploadCompleted.value = false
}

async function publish() {
  if (!draft.value) return
  const form = new FormData()
  form.append('draft_id', draft.value._id)
  if (selectedFile.value) form.append('file', selectedFile.value)
  try {
    const res = await axios.post('/api/content/publish', form, { headers: { 'Content-Type': 'multipart/form-data' } })
    // If backend returned an upload_url, perform client-side resumable upload
  if (res.data && res.data.upload_url && selectedFile.value) {
      uploadProgress.value = 0
      publishResult.value = 'Uploading to YouTube...'
      try {
    // reset cancel state
  currentUpload.canceled = false
  const meta = await performResumableUpload(res.data.upload_url, selectedFile.value, (p) => { uploadProgress.value = p })
        publishResult.value = 'Upload complete: ' + (meta ? JSON.stringify(meta, null, 2) : 'ok')
      } catch (err) {
    publishResult.value = 'Upload failed: ' + (err.message || err)
    if (currentUpload.canceled) publishResult.value = 'Upload canceled'
      }
      // refresh drafts; backend may still need to persist publish result
      await fetchDrafts()
      // reset progress and clear file input so Publish stays disabled until new selection
      uploadProgress.value = 0
      try {
        selectedFile.value = null
        if (fileInput.value) fileInput.value.value = ''
      } catch (e) {}
    } else if (res.status === 202) {
      publishJobId.value = res.data.job_id || ''
      publishResult.value = JSON.stringify(res.data, null, 2)
      await fetchDrafts()
    } else {
      publishResult.value = JSON.stringify(res.data, null, 2)
      await fetchDrafts()
    }
  } catch (err) {
    publishResult.value = 'Publish failed: ' + (err.response?.data?.error || err.message)
  }
}


function _sendChunkXHR(url, chunk, start, end, total, mime) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    // store current XHR so it can be aborted externally
    currentUpload.xhr = xhr
    xhr.open('PUT', url, true)
    xhr.setRequestHeader('Content-Type', mime || 'application/octet-stream')
    xhr.setRequestHeader('Content-Range', `bytes ${start}-${end}/${total}`)
    xhr.onload = function () {
      // 308 = Resume Incomplete (Google), 200/201 = final
      // clear stored xhr when chunk completes
      if (currentUpload.xhr === xhr) currentUpload.xhr = null
      resolve({ status: xhr.status, headers: xhr.getAllResponseHeaders(), body: xhr.responseText })
    }
    xhr.onerror = function (e) { if (currentUpload.xhr === xhr) currentUpload.xhr = null; reject(new Error('XHR error')) }
    xhr.onabort = function () { if (currentUpload.xhr === xhr) currentUpload.xhr = null; reject(new Error('XHR aborted')) }
    xhr.upload.onprogress = function (ev) {
      // client-level per-chunk progress available via outer closure
      // we'll resolve overall progress externally
    }
    xhr.send(chunk)
  })
}

async function performResumableUpload(uploadUrl, file, onProgress) {
  // chunked upload with Content-Range PUTs. onProgress receives 0..100
  const chunkSize = 10 * 1024 * 1024 // 10MB
  const total = file.size
  let offset = 0
  let uploaded = 0

  while (offset < total) {
    const end = Math.min(offset + chunkSize, total)
    const chunk = file.slice(offset, end)
    try {
  if (currentUpload.canceled) throw new Error('canceled')
      const resp = await _sendChunkXHR(uploadUrl, chunk, offset, end - 1, total, file.type)
      if (resp.status === 200 || resp.status === 201) {
        // final response
        if (onProgress) onProgress(100)
        try { return JSON.parse(resp.body || 'null') } catch (e) { return null }
      }
      if (resp.status === 308) {
        // parse Range header to know how much server received
        const hdrs = resp.headers || ''
        // headers string; look for 'Range: bytes=0-XXXXX' or similar
        const m = /Range:\s*bytes=0-(\d+)/i.exec(hdrs)
        if (m) {
          const last = parseInt(m[1], 10)
          uploaded = last + 1
          offset = uploaded
        } else {
          // fallback: advance by chunk size
          offset = end
          uploaded = offset
        }
      } else if (resp.status >= 200 && resp.status < 300) {
        if (onProgress) onProgress(Math.round((end / total) * 100))
        offset = end
        uploaded = offset
      } else {
        throw new Error('Upload failed with status ' + resp.status)
      }
    } catch (err) {
      // propagate cancellation as a clean abort
      if (currentUpload.canceled) throw new Error('canceled')
      throw err
    }
    if (onProgress) onProgress(Math.round((uploaded / total) * 100))
  }
  return null
}

function cancelUpload() {
  currentUpload.canceled = true
  try {
    if (currentUpload.xhr) currentUpload.xhr.abort()
  } catch (e) {
    // ignore
  }
  uploadProgress.value = 0
  publishResult.value = 'Upload canceled'
}

async function fetchDrafts() {
  try {
    const res = await axios.get('/api/drafts')
    draftsList.value = res.data || []
  } catch (err) {
    // ignore errors for now
    draftsList.value = []
  }
}

onMounted(() => {
  fetchDrafts()
})

async function startAuthorize() {
  if (!brandId.value) {
    status.value = 'Brand ID required to start OAuth.'
    return
  }
  status.value = 'Requesting authorize URL...'
  try {
    // Use backend authorize endpoint. The backend expects a redirect_uri parameter.
    const redirect = 'http://localhost:18000/api/oauth/youtube/callback'
    const res = await axios.get('/api/oauth/youtube/authorize', { params: { brand_id: brandId.value, redirect_uri: redirect } })
    authUrl.value = res.data.authorize_url
    if (authUrl.value) {
      status.value = 'Authorize URL received — opened in new tab.'
      // open automatically
      window.open(authUrl.value, '_blank')
    } else {
      status.value = 'No authorize URL returned.'
    }
  } catch (err) {
    status.value = 'Failed to get authorize URL: ' + (err.response?.data?.error || err.message)
  }
}

async function exchangeCode() {
  if (!brandId.value || !authCode.value) {
    status.value = 'Brand ID and code are required.'
    return
  }
  status.value = 'Exchanging code for token...'
  try {
    const body = { brand_id: brandId.value, code: authCode.value, redirect_uri: 'http://localhost:18000/api/oauth/youtube/callback' }
    const res = await axios.post('/api/oauth/youtube/callback', body)
    tokenResponse.value = JSON.stringify(res.data, null, 2)
    status.value = 'Token exchange complete.'
  } catch (err) {
    status.value = 'Token exchange failed: ' + (err.response?.data?.error || err.message)
  }
}

async function checkConnection() {
  if (!brandId.value) {
    status.value = 'Brand ID required.'
    return
  }
  status.value = 'Checking connection (attempting refresh)...'
  try {
    const res = await axios.post('/api/oauth/youtube/refresh', { brand_id: brandId.value })
    tokenResponse.value = JSON.stringify(res.data, null, 2)
    status.value = 'Refresh returned token.'
  } catch (err) {
    status.value = 'Refresh failed / no token: ' + (err.response?.data?.error || err.message)
  }
}

async function fetchMaskedStatus() {
  if (!brandId.value) return
  try {
    const res = await axios.get('/api/oauth/youtube/status', { params: { brand_id: brandId.value } })
    maskedStatus.value = res.data
  } catch (err) {
    maskedStatus.value = { connected: false }
  }
}

// Poll when platform is youtube
watch(platform, (v) => {
  if (v === 'youtube') {
    fetchMaskedStatus()
    if (statusInterval) clearInterval(statusInterval)
    statusInterval = setInterval(fetchMaskedStatus, 10000)
  } else {
    if (statusInterval) { clearInterval(statusInterval); statusInterval = null }
    maskedStatus.value = null
  }
})

// tear down interval when leaving the page (Nuxt client lifecycle)
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', () => { if (statusInterval) clearInterval(statusInterval) })
}
</script>

<style scoped>
.publish-btn {
  transition: opacity 120ms ease-in-out, transform 120ms ease-in-out;
  padding: 0.4rem 0.65rem;
  border-radius: 6px;
  border: 1px solid #3b82f6;
  background: #3b82f6;
  color: white;
}
.disabled-button {
  opacity: 0.55 !important;
  cursor: not-allowed !important;
  background: #93c5fd !important;
  border-color: #60a5fa !important;
}
</style>
