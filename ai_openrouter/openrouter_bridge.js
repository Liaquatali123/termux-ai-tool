/**
 * openrouter_bridge.js
 * Bridge between OpenCode tools and OpenRouter AI backend.
 * All inference routed through free model pool with auto-fallback.
 */

const AI_CONFIG = {
  basePath: '/storage/emulated/0/Download/ai_openrouter',
  apiBase: 'https://openrouter.ai/api/v1/chat/completions',
  modelsUrl: 'https://openrouter.ai/api/v1/models',
  activeModel: 'openrouter/free',
  timeout: 30000,
}

class OpenRouterBridge {
  constructor(apiKey) {
    this.apiKey = apiKey || ''
    this.activeModel = AI_CONFIG.activeModel
    this._loadState()
  }

  _loadState() {
    try {
      const fs = require('fs')
      const cfg = JSON.parse(fs.readFileSync(`${AI_CONFIG.basePath}/configs/models_config.json`, 'utf8'))
      if (cfg.working_models?.length) {
        this.activeModel = cfg.working_models[0]
        this._allModels = cfg.working_models
        this._details = cfg.model_details || {}
      }
    } catch {}
    try { const k = localStorage.getItem('openrouter_key'); if (k && !this.apiKey) this.apiKey = k } catch {}
  }

  setApiKey(key) { this.apiKey = key }

  /**
   * Send a completion request to OpenRouter via the active model.
   * Auto-fallback: if model fails, tries next working model immediately.
   */
  async complete(messages, options = {}) {
    if (!this.apiKey) throw new Error('No API key set')

    const maxTokens = options.max_tokens || 1024
    const temperature = options.temperature ?? 0.7
    const models = [
      this.activeModel,
      ...(this._allModels || []).filter(m => m !== this.activeModel),
      'openrouter/free',
    ]

    let lastError = ''

    for (const model of models) {
      try {
        const r = await fetch(AI_CONFIG.apiBase, {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${this.apiKey}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ model, messages, max_tokens: maxTokens, temperature }),
          signal: AbortSignal.timeout(options.timeout || AI_CONFIG.timeout),
        })

        if (r.ok) {
          const data = await r.json()
          this.activeModel = model
          return { success: true, data, model }
        }

        const body = await r.text()
        lastError = `${r.status}: ${body.slice(0, 200)}`

        const isOverloaded = /busy|overload|unavailable|503|502/i.test(body)
        if (isOverloaded) {
          this._markBusy(model, 30)
          continue
        }
        if (r.status === 429) {
          this._markBusy(model, 30)
          continue
        }
        if (r.status === 404) continue
      } catch (e) {
        lastError = e.message
        if (e.name === 'TimeoutError' || e.name === 'AbortError') continue
      }
    }

    return { success: false, error: lastError, model: this.activeModel }
  }

  /**
   * Quick ping a model to check if it's alive
   */
  async ping(modelId) {
    try {
      const r = await fetch(AI_CONFIG.apiBase, {
        method: 'POST',
        headers: { Authorization: `Bearer ${this.apiKey}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelId, messages: [{ role: 'user', content: 'ok' }], max_tokens: 3 }),
        signal: AbortSignal.timeout(10000),
      })
      if (r.ok) return 'healthy'
      if (r.status === 429) return 'rate_limited'
      return 'unhealthy'
    } catch { return 'timeout' }
  }

  /**
   * Get free model list from OpenRouter
   */
  async fetchFreeModels() {
    try {
      const r = await fetch(AI_CONFIG.modelsUrl, { signal: AbortSignal.timeout(10000) })
      if (!r.ok) return []
      const data = await r.json()
      return data.data.filter(m => m.id.includes(':free')).map(m => m.id)
    } catch { return [] }
  }

  _markBusy(model, minutes) {
    try {
      const fs = require('fs')
      const busyFile = `${AI_CONFIG.basePath}/cache/busy_models.json`
      let busy = {}
      try { busy = JSON.parse(fs.readFileSync(busyFile, 'utf8')) } catch {}
      busy[model] = { until: Date.now() + minutes * 1000, reason: 'overloaded' }
      fs.writeFileSync(busyFile, JSON.stringify(busy))
    } catch {}
  }

  getStatus() {
    return {
      active: this.activeModel,
      keySet: !!this.apiKey,
      available: this._allModels?.length || 0,
    }
  }
}

window.OpenRouterBridge = OpenRouterBridge
