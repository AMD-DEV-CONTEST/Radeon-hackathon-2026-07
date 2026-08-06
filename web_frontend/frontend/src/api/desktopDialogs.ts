import { invoke, isTauri } from '@tauri-apps/api/core'
import { ApiError, requestJson } from './http'

export class NativeDirectoryPickerUnavailableError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'NativeDirectoryPickerUnavailableError'
  }
}

export async function selectLocalDirectory(initialPath?: string): Promise<string | null> {
  if (isTauri()) {
    return invoke<string | null>('select_directory', {
      initialPath: initialPath?.trim() || null,
    })
  }
  try {
    const response = await requestJson<{ path: string | null }>('/api/workspace/select-directory', {
      method: 'POST',
      body: JSON.stringify({ initial_path: initialPath?.trim() || null }),
    })
    return response.path
  } catch (error) {
    if (error instanceof ApiError && [403, 503].includes(error.status)) {
      throw new NativeDirectoryPickerUnavailableError(error.message)
    }
    throw error
  }
}
