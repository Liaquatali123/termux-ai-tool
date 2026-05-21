/**
 * github_project_sync.js
 * Handles GitHub clone, pull, push, and project detection.
 * Works in Node.js (Termux) and browser environments.
 */

class GitHubSync {
  constructor() {
    this.projectsDir = '/storage/emulated/0/Projects'
    this._exec = null
    try { this._exec = require('child_process').execSync } catch {}
  }

  isNode() { return !!this._exec }

  /**
   * Parse a GitHub URL to extract owner/repo
   */
  parseUrl(url) {
    url = url.trim()
    let match = url.match(/github\.com[:\/]([\w-]+)\/([\w.-]+?)(?:\.git)?$/)
    if (!match) match = url.match(/^([\w-]+)\/([\w.-]+)$/)
    if (!match) return null
    return { owner: match[1], repo: match[2].replace(/\.git$/, ''), full: `${match[1]}/${match[2].replace(/\.git$/, '')}` }
  }

  /**
   * Clone a GitHub repo into Projects/
   */
  clone(url) {
    const parsed = this.parseUrl(url)
    if (!parsed) throw new Error('Invalid GitHub URL: ' + url)
    const name = parsed.repo
    const dest = `${this.projectsDir}/${name}`

    if (this.isNode()) {
      this._exec(`git clone "${url}" "${dest}" 2>&1`, { stdio: 'inherit' })
    }
    const type = this.detectProjectType(dest)
    return { path: dest, name, type, remote: url }
  }

  /**
   * Pull latest changes for a project
   */
  pull(projectPath) {
    const dir = projectPath || this.projectsDir
    if (this.isNode()) {
      try {
        this._exec(`cd "${dir}" && git pull --rebase 2>&1`, { stdio: 'inherit' })
        return true
      } catch { return false }
    }
    return false
  }

  /**
   * Stage, commit, and push changes
   */
  push(projectPath, commitMessage) {
    if (!this.isNode()) return false
    const dir = projectPath
    try {
      this._exec(`cd "${dir}" && git add -A 2>&1`, { stdio: 'inherit' })
      this._exec(`cd "${dir}" && git commit -m "${commitMessage || 'Auto-sync'}" 2>&1`, { stdio: 'inherit' })
      this._exec(`cd "${dir}" && git push 2>&1`, { stdio: 'inherit' })
      return true
    } catch {
      // Nothing to commit or push failed
      return false
    }
  }

  /**
   * Full sync: pull → commit → push
   */
  sync(projectPath, commitMessage) {
    if (!this.isNode()) return { pulled: false, pushed: false }
    const dir = projectPath
    const pulled = this.pull(dir)
    const pushed = this.push(dir, commitMessage)
    return { pulled, pushed }
  }

  /**
   * Detect project type from files
   */
  detectProjectType(projectPath) {
    try {
      const fs = require('fs')
      const files = fs.readdirSync(projectPath)
      if (files.includes('package.json')) return 'Node.js'
      if (files.includes('requirements.txt')) return 'Python'
      if (files.includes('Cargo.toml')) return 'Rust'
      if (files.includes('index.html')) return 'HTML/CSS/JS'
      if (files.includes('bot.py')) return 'Python Bot'
      if (files.includes('Dockerfile')) return 'Docker'
      if (files.includes('Makefile')) return 'C/C++'
      return 'Unknown'
    } catch {
      return 'Unknown'
    }
  }

  /**
   * List all projects with metadata
   */
  listProjects() {
    const projects = []
    try {
      const fs = require('fs')
      const dirs = fs.readdirSync(this.projectsDir)
      for (const d of dirs) {
        const full = `${this.projectsDir}/${d}`
        if (!fs.statSync(full).isDirectory()) continue
        const type = this.detectProjectType(full)
        let remote = ''
        let branch = ''
        try {
          remote = this._exec(`cd "${full}" && git remote get-url origin 2>/dev/null`, { encoding: 'utf8' }).trim()
          branch = this._exec(`cd "${full}" && git rev-parse --abbrev-ref HEAD 2>/dev/null`, { encoding: 'utf8' }).trim()
        } catch {}
        projects.push({ name: d, path: full, type, remote, branch })
      }
    } catch {}
    return projects
  }
}

window.GitHubSync = GitHubSync
