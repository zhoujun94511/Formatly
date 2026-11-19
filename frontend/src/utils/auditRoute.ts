import type { DocumentKind } from '../types'

export interface AuditDefaults { profile: string; kind: string; collection: string }

export function auditRoute(profile = '', kind: string = 'thesis', collection = '', revision = '') {
  const params = new URLSearchParams()
  if (profile) params.set('profile', profile)
  if (kind !== 'thesis') params.set('kind', kind)
  if (collection) params.set('collection', collection)
  if (revision) params.set('revision', revision)
  return `new${params.size ? `?${params}` : ''}`
}

export function auditDefaults(route: string): AuditDefaults | null {
  const [path, query] = route.split('?', 2)
  if (path !== 'new') return null
  const params = new URLSearchParams(query)
  const kind = params.get('kind') as DocumentKind | null
  return {
    profile: params.get('profile') || '',
    kind: kind && ['thesis', 'intern', 'certificate'].includes(kind) ? kind : 'thesis',
    collection: params.get('collection') || '',
  }
}
