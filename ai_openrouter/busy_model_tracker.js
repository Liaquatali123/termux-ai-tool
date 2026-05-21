/**
 * busy_model_tracker.js
 * Tracks which models are currently busy/overloaded.
 * Prevents routing to busy models for a configurable cooldown.
 */

class BusyModelTracker {
  constructor() {
    this._busy = {}
    this._penaltyDurations = {
      overloaded: 30000,
      rate_limited: 30000,
      timeout: 10000,
      error: 15000,
    }
    this._load()
  }

  markBusy(modelId, reason) {
    const duration = this._penaltyDurations[reason] || 15000
    this._busy[modelId] = {
      until: Date.now() + duration,
      reason,
      marked: Date.now(),
    }
    this._save()
  }

  isBusy(modelId) {
    const entry = this._busy[modelId]
    if (!entry) return false
    if (Date.now() > entry.until) {
      delete this._busy[modelId]
      this._save()
      return false
    }
    return true
  }

  getBusyUntil(modelId) {
    const entry = this._busy[modelId]
    if (!entry) return 0
    if (Date.now() > entry.until) {
      delete this._busy[modelId]
      this._save()
      return 0
    }
    return entry.until - Date.now()
  }

  clearBusy(modelId) {
    delete this._busy[modelId]
    this._save()
  }

  clearAll() {
    this._busy = {}
    this._save()
  }

  getAll() {
    const now = Date.now()
    for (const [m, e] of Object.entries(this._busy)) {
      if (now > e.until) delete this._busy[m]
    }
    return { ...this._busy }
  }

  _load() {
    try {
      const d = localStorage.getItem('am_busy_models')
      if (d) this._busy = JSON.parse(d)
    } catch {}
  }

  _save() {
    try {
      localStorage.setItem('am_busy_models', JSON.stringify(this._busy))
    } catch {}
  }
}

const busyTracker = new BusyModelTracker()
window.BusyModelTracker = BusyModelTracker
window.busyTracker = busyTracker
