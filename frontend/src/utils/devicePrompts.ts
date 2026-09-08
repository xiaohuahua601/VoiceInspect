export type PromptDevice = {
  name: string
  model: string
  metadata?: Record<string, unknown>
}

const promptSets: Record<string, string[]> = {
  compressor: [
    '{device} 出现压力波动，应该按什么顺序检查？',
    '如何判断 {device} 温度异常是冷却还是润滑问题？',
    '{device} 的安全阀和储气罐有哪些检查注意事项？',
  ],
  hydraulic_system: [
    '{device} 压力下降时，如何区分泄漏、阀滞后和蓄能器压力不足？',
    '{device} 液压泵温度升高应先检查哪些传感器和部件？',
    '如何根据 {device} 的传感器数据判断冷却器效率异常？',
  ],
  motor: [
    '{device} 电流波动时，应如何排查负载、轴承和驱动器？',
    '如何用 {device} 的转速、扭矩和振动信号判断驱动异常？',
    '{device} 启动失败前需要检查哪些安全项？',
  ],
  industrial_machine: [
    '{device} 出现工具磨损报警时，如何确认是否需要更换？',
    '{device} 温度与转速同时异常时，优先检查哪些因素？',
    '如何区分 {device} 的功率故障、过载和散热异常？',
  ],
}

function equipmentType(device?: PromptDevice) {
  const configured = device?.metadata?.equipment_type
  if (typeof configured === 'string' && configured) return configured
  const model = device?.model.toLowerCase() ?? ''
  if (model.includes('compressor')) return 'compressor'
  if (model.includes('hydraulic')) return 'hydraulic_system'
  if (model.includes('motor') || model.includes('drive')) return 'motor'
  return 'industrial_machine'
}

function configuredPrompts(device?: PromptDevice) {
  const prompts = device?.metadata?.quick_prompts
  return Array.isArray(prompts) ? prompts.filter((item): item is string => typeof item === 'string' && item.trim().length > 0) : []
}

export function getDevicePrompts(device?: PromptDevice): string[] {
  if (!device) return ['描述现场异常现象，应该先检查哪些方面？', '如何根据当前设备状态判断风险等级？', '请说明当前设备的安全检查要点。']
  const configured = configuredPrompts(device)
  const prompts = configured.length ? configured : (promptSets[equipmentType(device)] ?? promptSets.industrial_machine)
  return prompts.map((prompt) => prompt.split('{device}').join(device.name))
}

export function getDeviceTypeLabel(device?: PromptDevice): string {
  return ({ compressor: '空压机', hydraulic_system: '液压系统', motor: '驱动电机', industrial_machine: '通用工业设备' } as Record<string, string>)[equipmentType(device)] ?? '工业设备'
}