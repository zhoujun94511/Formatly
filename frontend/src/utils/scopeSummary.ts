import type { ScopeBinding, ScopeRequirement } from '../types'
import type { EffectiveSummary, ExpectedCapability } from './profileFields'

// This changes the capability preview only; a binding is not a detection result.
export function scopeSummaryOverlay(summary: EffectiveSummary, requirements: ScopeRequirement[], bindings: Record<string, ScopeBinding>, available: boolean) {
  const required = new Map(requirements.map(item => [item.id, item]))
  let updated = 0
  const items = summary.items.map(item => {
    const identity = item.requirement_id || item.id
    const requirement = identity && required.get(identity), binding = identity && bindings[identity]
    if (!requirement || !binding || requirement.target !== item.target || !['conditional', 'manual'].includes(item.state)) return item
    if (binding.status === 'unbound') {
      updated++
      return { ...item, state: 'manual' as const, reason: '本次暂不匹配，保留人工核对。', scope: [] }
    }
    if (!available || item.state === 'manual' && !/^须先确认(?:实际原稿的检查范围|正文段落样式范围)$/.test(item.reason)) return item
    updated++
    return { ...item, state: 'conditional' as const, reason: '已确认本次原稿范围；是否符合要求以检测报告为准。', scope: binding.style_ids || binding.section_indices || [] }
  })
  if (!updated) return { summary, updated }
  const states: ExpectedCapability[] = ['conditional', 'manual', 'unsupported', 'excluded', 'unavailable']
  const counts = Object.fromEntries(states.map(state => [state, items.filter(item => item.state === state).length])) as EffectiveSummary['counts']
  return { updated, summary: { ...summary, items, counts } }
}
