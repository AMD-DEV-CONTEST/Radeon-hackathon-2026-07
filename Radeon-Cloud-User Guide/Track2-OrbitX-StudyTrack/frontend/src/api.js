import axios from 'axios'

const apiUrl = (import.meta.env.VITE_API_URL || '').trim()

export const api = axios.create({
  baseURL: apiUrl.endsWith('/') ? apiUrl.slice(0, -1) : apiUrl,
})
