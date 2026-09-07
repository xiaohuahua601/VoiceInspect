import { afterEach, describe, expect, it } from 'vitest'
import { canAccess, clearAuth, getStoredUser, roleLabel, setAuth } from './api'

describe('enterprise auth helpers', () => {
  afterEach(() => clearAuth())
  it('maps enterprise roles to Chinese labels', () => {
    expect(roleLabel('maintenance_supervisor')).toBe('维修主管')
    expect(roleLabel('system_admin')).toBe('系统管理员')
  })
  it('enforces route role membership', () => {
    expect(canAccess('operator', ['operator', 'system_admin'])).toBe(true)
    expect(canAccess('operator', ['system_admin'])).toBe(false)
  })
  it('persists and restores auth context', () => {
    setAuth('token', { id: 'u1', username: 'operator', role: 'operator' })
    expect(getStoredUser()?.username).toBe('operator')
    expect(localStorage.getItem('voiceinspect_token')).toBe('token')
  })
})
