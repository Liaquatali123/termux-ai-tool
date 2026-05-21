/**
 * emergency_fallback.js
 * Last-resort fallback when ALL models fail.
 * Never throws. Never freezes. Always recovers.
 */

const EMERGENCY_CONFIG = {
  active: false,
  lastError: null,
  recoveryAttempts: 0,
  maxBackoff: 30000,
  backoffMs: 1000,
  retryTimers: [],
  emergencyModels: [
    'openrouter/free',
    'qwen/qwen3-coder:free',
    'deepseek/deepseek-v4-flash:free',
  ],
  blacklistRetryAfter: 60000,
}

class EmergencyFallback {
  constructor(manager) {
    this.mgr = manager
    this.cfg = { ...EMERGENCY_CONFIG }
    this._startRetryTimer()
    log('🚀', 'Emergency system armed')
  }

  isActive() { return this.cfg.active }

  async trigger(reason) {
    this.cfg.active = true
    this.cfg.lastError = reason
    this.cfg.recoveryAttempts++
    const backoff = Math.min(this.cfg.backoffMs, this.cfg.maxBackoff)
    log('⚠️', `EMERGENCY: ${reason} (attempt ${this.cfg.recoveryAttempts})`)
    log('⚠️', `Backoff: ${backoff}ms`)

    await new Promise(r => setTimeout(r, backoff))
    this.cfg.backoffMs = Math.min(this.cfg.backoffMs * 2, this.cfg.maxBackoff)

    const recovered = await this._attemptRecovery()
    if (recovered) {
      this.cfg.active = false
      this.cfg.backoffMs = 1000
      log('🚀', 'Emergency recovery complete')
    } else {
      log('⚠️', 'Recovery failed, will retry')
      this.trigger(reason)
    }
  }

  async _attemptRecovery() {
    // Try emergency models
    for (const m of this.cfg.emergencyModels) {
      if (this.mgr.cfg.blacklist.has(m)) continue
      const result = await this.mgr.testModel(m)
      if (result === true) {
        await this.mgr.switchModel(m)
        this.mgr.cfg.healthy = true
        this.mgr.cfg.workingModels.unshift(m)
        this.mgr._saveState()
        log('🚀', 'Emergency recovered on: ' + m)
        return true
      }
    }

    // Clear blacklist entirely and retry everything
    this.mgr.cfg.blacklist.clear()
    this.mgr.cfg.cooldowns = {}
    this.mgr._saveState()

    for (const m of this.mgr.cfg.fallbackOrder) {
      const result = await this.mgr.testModel(m)
      if (result === true) {
        await this.mgr.switchModel(m)
        this.mgr.cfg.healthy = true
        log('🚀', 'Full recovery on: ' + m)
        return true
      }
    }

    // Absolute last resort
    this.mgr.cfg.activeModel = 'openrouter/free'
    this.mgr.cfg.healthy = true
    this.mgr._saveState()
    this.mgr._notify()
    log('🚀', 'Force fallback to openrouter/free')
    return true
  }

  _startRetryTimer() {
    // Every 60s, retry blacklisted models
    setInterval(() => {
      const now = Date.now()
      for (const [m, t] of Object.entries(this.mgr.cfg.cooldowns)) {
        if (t < now) {
          delete this.mgr.cfg.cooldowns[m]
          log('🔄', 'Cooldown expired, retrying: ' + m)
        }
      }
    }, 60000)
  }

  safeResponse() {
    return {
      success: false,
      error: 'Service temporarily unavailable',
      model: 'emergency_fallback',
      data: { choices: [{ message: { content: '[System busy, retrying...]' } }] },
    }
  }
}

window.EmergencyFallback = EmergencyFallback
