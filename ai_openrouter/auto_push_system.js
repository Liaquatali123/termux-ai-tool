/**
 * auto_push_system.js
 * Watches projects and auto-pushes changes to GitHub.
 * Runs in background, debounced, never interrupts active session.
 */

class AutoPushSystem {
  constructor() {
    this.projectsDir = '/storage/emulated/0/Projects'
    this._debounceTimers = {}
    this._watchInterval = null
    this._watched = {}
    this._isNode = false
    try { this._exec = require('child_process').execSync; this._isNode = true } catch {}
    this._fs = null
    try { this._fs = require('fs') } catch {}
    this._debounceMs = 60000
    this._autoCommitEnabled = true
    this._lastPushes = {}
  }

  enable() { this._autoCommitEnabled = true }
  disable() { this._autoCommitEnabled = false }

  /**
   * Watch a project for file changes
   */
  watch(projectPath) {
    if (!this._isNode || !this._fs) return false
    const name = projectPath.split('/').pop()
    if (!this._fs.existsSync(projectPath)) return false

    this._watched[name] = projectPath
    this._lastPushes[name] = Date.now()

    if (!this._watchInterval) {
      this._watchInterval = setInterval(() => this._checkAll(), 30000)
    }
    return true
  }

  unwatch(name) {
    delete this._watched[name]
    delete this._lastPushes[name]
    if (Object.keys(this._watched).length === 0 && this._watchInterval) {
      clearInterval(this._watchInterval)
      this._watchInterval = null
    }
  }

  _checkAll() {
    for (const [name, path] of Object.entries(this._watched)) {
      this._checkProject(name, path)
    }
  }

  _checkProject(name, path) {
    if (!this._autoCommitEnabled) return
    if (!this._hasChanges(path)) return

    const elapsed = Date.now() - (this._lastPushes[name] || 0)
    if (elapsed < this._debounceMs) return

    const timerKey = `push_${name}`
    if (this._debounceTimers[timerKey]) {
      clearTimeout(this._debounceTimers[timerKey])
    }

    this._debounceTimers[timerKey] = setTimeout(() => {
      this._pushProject(name, path)
      this._lastPushes[name] = Date.now()
      delete this._debounceTimers[timerKey]
    }, 10000)
  }

  _hasChanges(path) {
    try {
      const out = this._exec(`cd "${path}" && git status --porcelain 2>/dev/null`, { encoding: 'utf8' }).trim()
      return out.length > 0
    } catch { return false }
  }

  _pushProject(name, path) {
    try {
      const timestamp = new Date().toISOString().slice(0, 19).replace('T', ' ')
      this._exec(`cd "${path}" && git add -A 2>&1`, { stdio: 'inherit' })
      this._exec(`cd "${path}" && git commit -m "Auto-sync ${timestamp}" 2>&1`, { stdio: 'inherit' })
      this._exec(`cd "${path}" && git push 2>&1`, { stdio: 'inherit' })
      console.log(`[AutoPush] ✅ ${name} pushed at ${timestamp}`)
    } catch {
      // No changes to push or git error — silent
    }
  }

  /**
   * Force push a specific project now
   */
  pushNow(projectPath, message) {
    if (!this._isNode) return false
    const name = projectPath.split('/').pop()
    this._pushProject(name, projectPath)
    return true
  }

  getStatus() {
    const status = { enabled: this._autoCommitEnabled, watching: {} }
    for (const [name, path] of Object.entries(this._watched)) {
      const hasChanges = this._hasChanges(path)
      const lastPush = this._lastPushes[name]
      status.watching[name] = {
        path,
        hasChanges,
        lastPush: lastPush ? new Date(lastPush).toISOString() : 'never',
      }
    }
    return status
  }

  stop() {
    if (this._watchInterval) {
      clearInterval(this._watchInterval)
      this._watchInterval = null
    }
    for (const t of Object.keys(this._debounceTimers)) {
      clearTimeout(this._debounceTimers[t])
    }
    this._debounceTimers = {}
    this._watched = {}
  }
}

window.AutoPushSystem = AutoPushSystem
