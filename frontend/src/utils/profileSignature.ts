import type { Profile } from '../types'

// A scheme ID can keep its name while its executable rules change.
export function profileRuleSignature(profile?: Profile) {
  return profile ? JSON.stringify([profile.id, profile.version, profile.plugins, profile.settings, profile.kinds, profile.school, profile.requirements, profile.scoped_rules]) : ''
}
