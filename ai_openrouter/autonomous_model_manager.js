/**
 * autonomous_model_manager.js
 * Smart model routing: task-aware, latency-optimized, zero-interruption.
 * Never interrupts app. Never shows errors to user.
 */

const CFG = {
  apiKey: '',
  activeModel: 'openrouter/free',
  workingModels: [],
  blacklist: new Set(),
  cooldowns: {},
  modelScores: {},
  requestQueue: [],
  processing: false,
  healthy: true,
  monitorInterval: null,
  scanInterval: null,
  statusListeners: [],
  fallbackOrder: ['openrouter/free'],
  categories: {},
  API_BASE: 'https://openrouter.ai/api/v1/chat/completions',
  MODELS_URL: 'https://openrouter.ai/api/v1/models',
}

const TASK_PATTERNS = {
  coding: [/code|script|function|debug|compile|syntax|react|api|endpoint|sql|python|javascript|html|css/i,
           /implement|refactor|optimize|algorithm|data structure|bug fix|unit test/i],
  fast: [/hi|hello|yes|no|ok|thanks|bye|quick|short|brief|simple|summary/i],
  reasoning: [/why|explain|analyze|compare|evaluate|what if|think|reason|logic|strategy|complex/i,
              /philosophy|science|math|proof|theory|hypothesis|implications/i],
}

const CATEGORY_KEYWORDS = {
  coding: ['coder', 'deepseek'],
  fast: ['nano', 'mini', 'light', '3b', '1.2b', 'xs', 'small', 'tiny', 'fast', 'flash'],
  reasoning: ['reasoning', 'think', 'deep', 'r1', 'large'],
}

const CATEGORY_PRIORITY = { coding: 0, fast: 1, reasoning: 2, general: 3 }

function log(emoji, msg) { console.log(`[${emoji} ModelRouter] ${msg}`) }

function detectTask(messages) {
  const text = (messages.map(m => m.content || '').join(' ')).slice(0, 2000)
  for (const [task, patterns] of Object.entries(TASK_PATTERNS)) {
    for (const p of patterns) { if (p.test(text)) return task }
  }
  return 'general'
}

function categorizeModel(id) {
  const name = id.toLowerCase()
  for (const [cat, keywords] of Object.entries(CATEGORY_KEYWORDS)) {
    for (const kw of keywords) { if (name.includes(kw)) return cat }
  }
  return 'general'
}

function computeScore(model, details, avgLatency) {
  const d = details || {}
  const health = d.health_score ?? 50
  const latency = avgLatency || d.avg_latency || 9999
  const latencySec = latency / 1000
  let score = 0
  score += Math.min(health, 100) * 0.4
  score += Math.max(0, 10 - latencySec) * 4
  if (d.category && CATEGORY_PRIORITY[d.category] !== undefined) {
    score += (3 - CATEGORY_PRIORITY[d.category]) * 2
  }
  if (latencySec > 5) score *= 0.5
  if (latencySec > 10) score *= 0.3
  if (d.hits > 5 && d.misses === 0) score += 10
  if (health < 20) score *= 0.3
  return Math.max(0, Math.round(score))
}

class SmartModelRouter {
  constructor(apiKey) {
    Object.assign(this, { cfg: CFG })
    this.cfg = { ...CFG }
    this.cfg.modelScores = {}
    this.cfg.categories = {}
    if (apiKey) this.cfg.apiKey = apiKey
    this._loadState()
    this._initConfig()
    log('🚀', 'Smart router ready')
  }

  _loadState() {
    try {
      const s = JSON.parse(localStorage.getItem('am_state') || '{}')
      if (s.activeModel) this.cfg.activeModel = s.activeModel
      if (s.workingModels) this.cfg.workingModels = s.workingModels
      if (s.blacklist) this.cfg.blacklist = new Set(s.blacklist)
      if (s.cooldowns) this.cfg.cooldowns = s.cooldowns
      if (s.modelScores) this.cfg.modelScores = s.modelScores
      if (s.categories) this.cfg.categories = s.categories
    } catch {}
    try { const k = localStorage.getItem('openrouter_key'); if (k && !this.cfg.apiKey) this.cfg.apiKey = k } catch {}
  }

  _saveState() {
    try {
      localStorage.setItem('am_state', JSON.stringify({
        activeModel: this.cfg.activeModel,
        workingModels: this.cfg.workingModels,
        blacklist: [...this.cfg.blacklist],
        cooldowns: this.cfg.cooldowns,
        modelScores: this.cfg.modelScores,
        categories: this.cfg.categories,
      }))
    } catch {}
  }

  async _initConfig() {
    try {
      const r = await fetch(this.cfg.MODELS_URL, { signal: AbortSignal.timeout(8000) })
      if (r.ok) {
        const data = await r.json()
        const free = data.data.filter(m => m.id.includes(':free')).map(m => m.id)
        if (free.length > 10) this.cfg._allFreeModels = free
      }
    } catch {}
    try {
      const r = await fetch('/storage/emulated/0/Download/ai_openrouter/configs/models_config.json')
      if (r.ok) {
        const cfg = await r.json()
        if (cfg.fallback_order?.length) this.cfg.fallbackOrder = cfg.fallback_order
        if (cfg.working_models?.length) {
          this.cfg.workingModels = cfg.working_models
          this.cfg.activeModel = cfg.working_models[0]
        }
        if (cfg.model_details) {
          this.cfg._details = cfg.model_details
          for (const [id, d] of Object.entries(cfg.model_details)) {
            this.cfg.categories[id] = d.category || categorizeModel(id)
            this.cfg.modelScores[id] = computeScore(id, d)
          }
        }
      }
    } catch {}
  }

  setApiKey(key) { this.cfg.apiKey = key; try { localStorage.setItem('openrouter_key', key) } catch {} }

  getActiveModel() { return this.cfg.activeModel }
  getStatus() {
    return {
      active: this.cfg.activeModel,
      working: this.cfg.workingModels.length,
      queue: this.cfg.requestQueue.length,
      healthy: this.cfg.healthy,
      blacklisted: this.cfg.blacklist.size,
    }
  }
  onStatusChange(cb) { this.cfg.statusListeners.push(cb) }
  _notify() { const s = this.getStatus(); this.cfg.statusListeners.forEach(cb => cb(s)) }

  async testModel(modelId) {
    if (!this.cfg.apiKey) return false
    try {
      const r = await fetch(this.cfg.API_BASE, {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + this.cfg.apiKey, 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelId, messages: [{ role: 'user', content: 'ok' }], max_tokens: 3, temperature: 0 }),
        signal: AbortSignal.timeout(10000),
      })
      if (r.ok) return true
      if (r.status === 429) return 'rate_limited'
      if (r.status === 404) return 'not_found'
      return false
    } catch { return 'timeout' }
  }

  /**
   * Pick the best model for a given task.
   * Uses scored ranking: health → latency → category match.
   */
  pickBestModel(taskType, currentModel) {
    const now = Date.now()
    const scored = []

    const candidates = [...new Set([...this.cfg.workingModels, ...this.cfg.fallbackOrder, 'openrouter/free'])]

    for (const m of candidates) {
      if (!m) continue
      if (m === currentModel) continue
      if (this.cfg.blacklist.has(m)) continue
      if (this.cfg.cooldowns[m] && this.cfg.cooldowns[m] > now) continue
      if (typeof busyTracker !== 'undefined' && busyTracker.isBusy(m)) continue

      const cat = this.cfg.categories[m] || categorizeModel(m)
      const d = this.cfg._details?.[m] || {}
      const latency = d.avg_latency || 9999
      const health = d.health_score ?? 50

      let score = computeScore(m, d)

      if (taskType === 'coding' && cat === 'coding') score += 30
      else if (taskType === 'coding' && cat === 'reasoning') score += 15

      if (taskType === 'fast' && cat === 'fast') score += 30

      if (taskType === 'reasoning' && cat === 'reasoning') score += 30
      else if (taskType === 'reasoning' && cat === 'coding') score += 10

      if (m === 'openrouter/free') score += 5

      scored.push({ model: m, score, latency, health, category: cat })
    }

    scored.sort((a, b) => b.score - a.score || a.latency - b.latency)

    return scored.length > 0 ? scored[0].model : null
  }

  async switchModel(newModel) {
    if (!newModel || this.cfg.activeModel === newModel) return
    log('🔄', this.cfg.activeModel + ' → ' + newModel)
    this.cfg.activeModel = newModel
    this.cfg.healthy = true
    this._saveState()
    this._notify()
    if (this.cfg.requestQueue.length > 0) this._processQueue()
  }

  async handleFailure(errorType, modelId) {
    const model = modelId || this.cfg.activeModel
    const emoji = errorType === 'overloaded' ? '⚠️' : errorType === 'rate_limited' ? '⏳' : '❌'
    log(emoji, model + ': ' + errorType)

    if (errorType === 'overloaded') {
      this.cfg.cooldowns[model] = Date.now() + 30000
      if (typeof busyTracker !== 'undefined') busyTracker.markBusy(model, 'overloaded')
    } else if (errorType === 'not_found' || errorType === 404) {
      this.cfg.blacklist.add(model)
      log('❌', model + ' blacklisted')
    } else if (errorType === 'rate_limited' || errorType === 429) {
      this.cfg.cooldowns[model] = Date.now() + 30000
      log('⏳', model + ' cooldown 30s')
    } else if (errorType === 'timeout') {
      this.cfg.cooldowns[model] = Date.now() + 5000
    } else if (errorType === 'empty') {
      this.cfg.blacklist.add(model)
    }

    const next = this.pickBestModel('general', model)
    if (next) { await this.switchModel(next); log('🚀', '→ ' + next) }
    else {
      this.cfg.healthy = false
      log('⚠️', 'All models exhausted, emergency')
      await this._emergencyRecovery()
    }
    this._saveState()
  }

  async _emergencyRecovery() {
    log('🚀', 'Emergency scan...')
    this.cfg.blacklist.clear()
    if (typeof busyTracker !== 'undefined') busyTracker.clearAll()

    const emergencyOrder = [
      'nvidia/nemotron-3-nano-30b-a3b:free',
      'liquid/lfm-2.5-1.2b-instruct:free',
      'nvidia/nemotron-3-super-120b-a12b:free',
      'openrouter/free',
    ]

    for (const m of emergencyOrder) {
      const r = await this.testModel(m)
      if (r === true) {
        this.cfg.workingModels.unshift(m)
        await this.switchModel(m)
        log('🚀', 'Emergency → ' + m)
        return
      }
    }

    for (const m of this.cfg.fallbackOrder) {
      const r = await this.testModel(m)
      if (r === true) { this.cfg.workingModels.unshift(m); await this.switchModel(m); return }
    }

    this.cfg.activeModel = 'openrouter/free'
    this.cfg.healthy = true
    log('🚀', 'Emergency → openrouter/free')
    this._saveState()
  }

  /**
   * Queue a request with auto-routing.
   * options.task: 'coding' | 'fast' | 'reasoning' | 'general' (auto-detected if omitted)
   */
  queueRequest(messages, options = {}) {
    return new Promise((resolve, reject) => {
      this.cfg.requestQueue.push({ messages, options, resolve, reject })
      if (!this.cfg.processing) this._processQueue()
    })
  }

  async _processQueue() {
    if (this.cfg.processing || this.cfg.requestQueue.length === 0) return
    this.cfg.processing = true
    while (this.cfg.requestQueue.length > 0) {
      const req = this.cfg.requestQueue.shift()
      try { req.resolve(await this._makeCall(req.messages, req.options)) }
      catch (e) { req.reject(e) }
    }
    this.cfg.processing = false
  }

  async _makeCall(messages, options) {
    const taskType = options.task || detectTask(messages)
    const maxRetries = Math.min(this.cfg.fallbackOrder.length + 3, 10)
    let model = this.cfg.activeModel
    let attempts = 0
    let lastError = ''

    while (attempts < maxRetries) {
      attempts++
      try {
        const r = await fetch(this.cfg.API_BASE, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.cfg.apiKey, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model,
            messages,
            max_tokens: options.max_tokens || 1024,
            temperature: options.temperature ?? 0.7,
          }),
        })
        if (r.ok) {
          this.cfg.activeModel = model
          this.cfg.healthy = true
          if (typeof busyTracker !== 'undefined') busyTracker.clearBusy(model)
          this._saveState()
          this._notify()
          return { success: true, data: await r.json(), model }
        }

        const bodyText = await r.text()
        let bodyJson
        try { bodyJson = JSON.parse(bodyText) } catch {}
        const errType = detectErrorType(bodyJson || bodyText, r.status)
        lastError = errType

        if (errType === 'overloaded') {
          log('⚠️', model + ' overloaded — instant switch')
          this.cfg.cooldowns[model] = Date.now() + 30000
          if (typeof busyTracker !== 'undefined') busyTracker.markBusy(model, 'overloaded')
          model = this.pickBestModel(taskType, model) || 'openrouter/free'
          this.cfg.activeModel = model
          this._notify()
          continue
        }
        if (errType === 'rate_limited') {
          this.cfg.cooldowns[model] = Date.now() + 30000
          model = this.pickBestModel(taskType, model) || 'openrouter/free'
          this.cfg.activeModel = model
          this._notify()
          await new Promise(r => setTimeout(r, 300))
          continue
        }
        if (errType === 'not_found') {
          this.cfg.blacklist.add(model)
          model = this.pickBestModel(taskType, model) || 'openrouter/free'
          this.cfg.activeModel = model
          this._notify()
          continue
        }
        this.cfg.cooldowns[model] = Date.now() + 10000
        model = this.pickBestModel(taskType, model) || 'openrouter/free'
        this.cfg.activeModel = model
        this._notify()
      } catch (e) {
        lastError = 'timeout'
        model = this.pickBestModel(taskType, model) || 'openrouter/free'
        this.cfg.activeModel = model
        this._notify()
      }
    }
    return { success: false, error: 'Exhausted: ' + lastError, model: this.cfg.activeModel }
  }

  startBackgroundMonitor() {
    log('✅', 'Monitor started (30s interval)')
    if (this.cfg.monitorInterval) clearInterval(this.cfg.monitorInterval)
    this.cfg.monitorInterval = setInterval(() => this._healthCheck(), 30000)
    if (this.cfg.scanInterval) clearInterval(this.cfg.scanInterval)
    this.cfg.scanInterval = setInterval(() => this.discoverNewModels(), 300000)
    setTimeout(() => this._healthCheck(), 5000)
    setTimeout(() => this.discoverNewModels(), 15000)
  }

  stopBackgroundMonitor() {
    if (this.cfg.monitorInterval) { clearInterval(this.cfg.monitorInterval); this.cfg.monitorInterval = null }
    if (this.cfg.scanInterval) { clearInterval(this.cfg.scanInterval); this.cfg.scanInterval = null }
  }

  async _healthCheck() {
    if (!this.cfg.apiKey) return
    const result = await this.testModel(this.cfg.activeModel)
    if (result === true) log('✅', this.cfg.activeModel + ' healthy')
    else if (result === 'rate_limited') await this.handleFailure('rate_limited')
    else if (result === 'not_found') await this.handleFailure('not_found')
    else await this.handleFailure('timeout')
    const now = Date.now()
    for (const [m, t] of Object.entries(this.cfg.cooldowns)) { if (t < now) delete this.cfg.cooldowns[m] }
  }

  async discoverNewModels() {
    log('🧠', 'Scanning for new free models...')
    try {
      const r = await fetch(this.cfg.MODELS_URL, { signal: AbortSignal.timeout(15000) })
      if (!r.ok) throw new Error('HTTP ' + r.status)
      const data = await r.json()
      const freeModels = data.data.filter(m => m.id.includes(':free')).map(m => m.id)
      log('🧠', 'Found ' + freeModels.length + ' free models')
      this.cfg._allFreeModels = freeModels
      let discovered = 0
      for (const m of freeModels) {
        if (this.cfg.blacklist.has(m) || this.cfg.workingModels.includes(m) || this.cfg.fallbackOrder.includes(m)) continue
        const result = await this.testModel(m)
        if (result === true) {
          this.cfg.workingModels.unshift(m)
          this.cfg.fallbackOrder.unshift(m)
          this.cfg.categories[m] = categorizeModel(m)
          discovered++
          log('🧠', 'New: ' + m)
        }
        await new Promise(r => setTimeout(r, 200))
      }
      if (discovered > 0) {
        log('🚀', discovered + ' new models added')
        this._saveState()
      }
    } catch (e) { log('⚠️', 'Scan: ' + e.message) }
  }

  syncToFile() {
    try {
      const fs = require('fs')
      const payload = {
        timestamp: new Date().toISOString(),
        activeModel: this.cfg.activeModel,
        working_models: this.cfg.workingModels,
        fallback_order: this.cfg.fallbackOrder,
        blacklist: [...this.cfg.blacklist],
        cooldowns: this.cfg.cooldowns,
        modelScores: this.cfg.modelScores,
        categories: this.cfg.categories,
        healthy: this.cfg.healthy,
      }
      fs.writeFileSync('/storage/emulated/0/Download/ai_openrouter/configs/models_config.json',
        JSON.stringify(payload, null, 2))
    } catch {
      try { localStorage.setItem('am_sync', JSON.stringify(payload)) } catch {}
    }
  }
}

window.SmartModelRouter = SmartModelRouter
window.AutonomousModelManager = SmartModelRouter
