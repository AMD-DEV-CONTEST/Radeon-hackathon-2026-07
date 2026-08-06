import { get, post, put } from './client.js'


export const getModelRuntimeResources = () => get('/model-runtime/resources')

export const getModelRuntimePolicy = () => get('/model-runtime/policy')

export const updateModelRuntimePolicy = (payload) =>
  put('/model-runtime/policy', payload)

export const evaluateModelAdmission = (payload) =>
  post('/model-runtime/admissions', payload)

export const listModelRuntimeLeases = (activeOnly = false) =>
  get('/model-runtime/leases', { active_only: activeOnly })

export const listModelRuntimeDrift = (activeOnly = true) =>
  get('/model-runtime/drift', { active_only: activeOnly })

export const reconcileModelRuntimeDrift = () =>
  post('/model-runtime/drift/reconcile', {})

export const listModelRuntimeEvidence = () =>
  get('/model-runtime/runtime-evidence')

export const listModelCoexistenceEvidence = () =>
  get('/model-runtime/coexistence-evidence')

export const listModelWorkers = () => get('/model-runtime/workers')

export const startModelWorker = (payload) =>
  post('/model-runtime/workers', payload)

export const getModelWorker = (workerId) =>
  get(`/model-runtime/workers/${encodeURIComponent(workerId)}`)

export const loadModelWorker = (workerId, payload) =>
  post(`/model-runtime/workers/${encodeURIComponent(workerId)}/load`, payload)

export const unloadModelWorker = (workerId) =>
  post(`/model-runtime/workers/${encodeURIComponent(workerId)}/unload`, {})

export const stopModelWorker = (workerId) =>
  post(`/model-runtime/workers/${encodeURIComponent(workerId)}/stop`, {})

export const probeModelWorker = (workerId, payload) =>
  post(`/model-runtime/workers/${encodeURIComponent(workerId)}/probe`, payload)

export const listModelRuntimeJobs = (workerId = null, limit = 100) =>
  get('/model-runtime/jobs', { worker_id: workerId, limit })

export const getModelRuntimeJob = (jobId) =>
  get(`/model-runtime/jobs/${encodeURIComponent(jobId)}`)

export const cancelModelRuntimeJob = (jobId) =>
  post(`/model-runtime/jobs/${encodeURIComponent(jobId)}/cancel`, {})
