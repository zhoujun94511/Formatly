import type { Profile, School } from '../types'

export function resolveSchoolProfiles(school: School | null, profiles: Profile[]): Profile[] {
  if (!school || school.status !== 'confirmed' || !Number.isInteger(school.version) || (school.version ?? 0) < 1) return []

  const available = new Map(profiles.map(profile => [profile.id, profile]))
  const resolved: Profile[] = []
  const seen = new Set<string>()
  for (const reference of school.profiles || []) {
    const id = typeof reference === 'string' ? reference : reference.id
    const profile = available.get(id) ?? (typeof reference === 'string' ? undefined : reference)
    if (!profile || seen.has(id) || profile.school?.id !== school.id
      || profile.school.version !== school.version || profile.version !== school.version) continue
    seen.add(id)
    resolved.push(profile)
  }
  return resolved
}
