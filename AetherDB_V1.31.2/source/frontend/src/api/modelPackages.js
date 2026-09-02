import { get, post } from './client.js'

export const listModelPackages = () => get('/model-packages')

export const getModelPackage = (packageId) =>
  get(`/model-packages/${encodeURIComponent(packageId)}`)

export const acceptModelPackageLicense = (packageId, payload) =>
  post(`/model-packages/${encodeURIComponent(packageId)}/license-acceptance`, payload)

export const installModelPackage = (packageId, payload) =>
  post(`/model-packages/${encodeURIComponent(packageId)}/install`, payload)

export const repairModelPackage = (packageId, payload) =>
  post(`/model-packages/${encodeURIComponent(packageId)}/repair`, payload)

export const verifyModelPackage = (packageId, packageVersion) =>
  post(`/model-packages/${encodeURIComponent(packageId)}/verify`, {
    package_version: packageVersion,
  })

export const uninstallModelPackage = (packageId, packageVersion) =>
  post(`/model-packages/${encodeURIComponent(packageId)}/uninstall`, {
    package_version: packageVersion,
    confirm_package_id: packageId,
  })

export const disableModelPackage = (packageId) =>
  post(`/model-packages/${encodeURIComponent(packageId)}/disable`, {})

export const enableModelPackage = (packageId) =>
  post(`/model-packages/${encodeURIComponent(packageId)}/enable`, {})

export const listModelPackageOperations = (limit = 20) =>
  get('/model-packages/operations', { limit })

export const checkModelPackageDistribution = (packages) =>
  post('/model-packages/distribution-check', { packages })

export const getModelPackageOperation = (operationId) =>
  get(`/model-packages/operations/${encodeURIComponent(operationId)}`)

export const cancelModelPackageOperation = (operationId) =>
  post(`/model-packages/operations/${encodeURIComponent(operationId)}/cancel`, {})

export const retryModelPackageOperation = (operationId) =>
  post(`/model-packages/operations/${encodeURIComponent(operationId)}/retry`, {})
