import { describe, expect, it } from 'vitest'
import { getDevicePrompts, getDeviceTypeLabel } from './devicePrompts'

describe('device-aware diagnosis prompts', () => {
  it('uses configured prompts for the selected device', () => {
    const prompts = getDevicePrompts({ name: '液压试验台 H-01', model: 'HYDRAULIC-SYSTEM-A', metadata: { equipment_type: 'hydraulic_system' } })
    expect(prompts[0]).toContain('液压试验台 H-01')
    expect(prompts[0]).toContain('蓄能器')
    expect(prompts[0]).not.toContain('空压机')
    expect(getDeviceTypeLabel({ name: '液压试验台 H-01', model: 'HYDRAULIC-SYSTEM-A', metadata: { equipment_type: 'hydraulic_system' } })).toBe('液压系统')
  })

  it('prefers device metadata templates over type defaults', () => {
    const prompts = getDevicePrompts({ name: '自定义设备', model: 'MOTOR-DRIVE-A', metadata: { quick_prompts: ['检查 {device} 的专用联锁。'] } })
    expect(prompts).toEqual(['检查 自定义设备 的专用联锁。'])
  })
})