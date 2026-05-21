/**
 * smart_retry_system.js
 * Per-error-type retry strategies with exponential backoff.
 */

const RETRY_CONFIG = {
  strategies: {
    429: { label: 'rate_limited', backoff: [1000, 2000, 4000, 8000], maxTries: 4, cooldown: 30000, action: 'cooldown_then_switch' },
    404: { label: 'not_found', backoff: [0], maxTries: 1, cooldown: -1, action: 'blacklist_switch' },
    timeout: { label: 'timeout', backoff: [100, 200, 500], maxTries: 3, cooldown: 5000, action: 'switch_instant' },
    empty: { label: 'empty_response', backoff: [0, 1000], maxTries: 2, cooldown: 10000, action: 'retry_then_switch' },
    network: { label: 'network_error', backoff: [500, 1000, 2000, 4000], maxTries: 4, cooldown: 15000, action: 'switch_after_retries' },
  },
  modelStats: {},
}

class SmartRetrySystem {
  constructor(manager) {
    this.mgr = manager
    this.cfg = { ...RETRY_CONFIG }
    this.modelStats = {}
    this._loadStats()
  }

  _loadStats() {
    try {
      const s = localStorage.getItem('sr_retry_stats')
      if (s) this.modelStats = JSON.parse(s)
    } catch {}
  }
  _saveStats() {
    try { localStorage.setItem('sr_retry_stats', JSON.stringify(this.modelStats)) } catch {}
  }

  getStrategy(errorType) {
    return this.cfg.strategies[errorType] || this.cfg.strategies.network
  }

  async execute(modelId, errorType, callFn) {
    const strategy = this.getStrategy(errorType)
    const stats = this._getModelStats(modelId)
    stats.totalErrors = (stats.totalErrors || 0) + 1
    stats.lastError = errorType
    stats.lastErrorAt = Date.now()

    log('🔄', `[Retry] ${modelId} → ${strategy.label} (attempt ${stats.consecutiveErrors+1}/${strategy.maxTries})`)

    if (strategy.action === 'blacklist_switch') {
      // 404: immediate blacklist + switch
      const next = this.mgr._findNextWorking()
      if (next) await this.mgr.switchModel(next)
      this.mgr.cfg.blacklist.add(modelId)
      stats.blacklisted = true
      this._saveStats()
    }

    if (strategy.action === 'cooldown_then_switch') {
      // 429: try with backoff, then switch
      for (let i = 0; i < strategy.backoff.length; i++) {
        const delay = strategy.backoff[i]
        stats.consecutiveErrors = i + 1
        await new Promise(r => setTimeout(r, delay))
        const ok = await this.mgr.testModel(modelId)
        if (ok === true) {
          stats.consecutiveErrors = 0
          this._saveStats()
          return await callFn()
        }
        if (ok === 'rate_limited') continue
        break
      }
      // Exhausted retries, cooldown + switch
      this.mgr.cfg.cooldowns[modelId] = Date.now() + strategy.cooldown
      const next = this.mgr._findNextWorking()
      if (next) await this.mgr.switchModel(next)
    }

    if (strategy.action === 'switch_instant') {
      // timeout: switch immediately
      const next = this.mgr._findNextWorking()
      if (next) await this.mgr.switchModel(next)
      this.mgr.cfg.cooldowns[modelId] = Date.now() + strategy.cooldown
    }

    if (strategy.action === 'retry_then_switch') {
      // empty response: retry once, then switch
      if (stats.consecutiveErrors < strategy.maxTries) {
        stats.consecutiveErrors = (stats.consecutiveErrors || 0) + 1
        this._saveStats()
        const delay = strategy.backoff[Math.min(stats.consecutiveErrors - 1, strategy.backoff.length - 1)]
        await new Promise(r => setTimeout(r, delay))
        return await callFn()
      }
      const next = this.mgr._findNextWorking()
      if (next) await this.mgr.switchModel(next)
      this.mgr.cfg.cooldowns[modelId] = Date.now() + strategy.cooldown
    }

    if (strategy.action === 'switch_after_retries') {
      for (let i = 0; i < strategy.backoff.length; i++) {
        const delay = strategy.backoff[i]
        await new Promise(r => setTimeout(r, delay))
        try {
          return await callFn()
        } catch {}
      }
      const next = this.mgr._findNextWorking()
      if (next) await this.mgr.switchModel(next)
      this.mgr.cfg.cooldowns[modelId] = Date.now() + strategy.cooldown
    }

    stats.consecutiveErrors = (stats.consecutiveErrors || 0) + 1
    this._saveStats()

    // If all strategies exhausted, trigger emergency
    if (this.mgr._findNextWorking() === null) {
      log('⚠️', '[Retry] All models exhausted, triggering emergency')
      const emerg = new EmergencyFallback(this.mgr)
      await emerg.trigger('All models exhausted after retries')
    }

    return null
  }

  _getModelStats(modelId) {
    if (!this.modelStats[modelId]) this.modelStats[modelId] = { consecutiveErrors: 0, totalErrors: 0, lastError: null, lastErrorAt: null, blacklisted: false }
    return this.modelStats[modelId]
  }

  getModelHealth() {
    return Object.entries(this.modelStats).map(([m, s]) => ({
      model: m,
      errors: s.totalErrors || 0,
      lastError: s.lastError,
      healthy: !s.blacklisted && ((s.consecutiveErrors || 0) < 3),
    }))
  }
}

window.SmartRetrySystem = SmartRetrySystem
