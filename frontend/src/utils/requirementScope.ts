import type { Requirement } from '../types'

type SectionRequirement = Pick<Requirement, 'target' | 'scope_section_indices' | 'parameters' | 'scope_binding_status'>

export function clearGlobalSectionBinding(item: SectionRequirement) {
  // Only page and section properties support an empty selector meaning all sections.
  if (!item.target.startsWith('page.') && !item.target.startsWith('section.')) return
  const sections = item.scope_section_indices?.length ? item.scope_section_indices : item.parameters?.section_indices
  if (!Array.isArray(sections) || !sections.length) delete item.scope_binding_status
}

export function updateRequirementSections(item: SectionRequirement, sections: number[]) {
  item.scope_section_indices = [...sections]
  if (Array.isArray(item.parameters?.section_indices)) item.parameters.section_indices = [...sections]
  clearGlobalSectionBinding(item)
}
