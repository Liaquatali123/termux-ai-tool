/**
 * project_loader.js
 * Auto-detects project type and loads into development environment.
 */

class ProjectLoader {
  constructor() {
    this.projectsDir = '/storage/emulated/0/Projects'
    this.supported = {
      'Node.js': ['package.json', 'server.js', 'app.js', 'index.js'],
      'Python': ['requirements.txt', 'main.py', 'bot.py', 'app.py'],
      'HTML/CSS/JS': ['index.html', 'style.css', 'app.js'],
      'Rust': ['Cargo.toml', 'src/main.rs', 'src/lib.rs'],
      'React': ['package.json', 'src/App.js', 'src/App.jsx', 'vite.config.js'],
      'Game': ['index.html', 'game.js', 'phaser.js'],
      'AI Project': ['model.py', 'train.py', 'config.json'],
    }
  }

  /**
   * Load/detect a project by path or name
   */
  load(projectPath) {
    const fs = require('fs')
    const path = require('path')

    const fullPath = projectPath.startsWith('/') ? projectPath : `${this.projectsDir}/${projectPath}`
    if (!fs.existsSync(fullPath)) throw new Error(`Project not found: ${fullPath}`)

    const type = this.detectType(fullPath)
    const files = this.scanFiles(fullPath)
    const git = this.detectGit(fullPath)

    return {
      name: path.basename(fullPath),
      path: fullPath,
      type,
      files,
      git,
      entry: this.findEntry(fullPath, type),
    }
  }

  /**
   * Detect project type
   */
  detectType(projectPath) {
    const fs = require('fs')
    let files = []
    try { files = fs.readdirSync(projectPath) } catch { return 'Unknown' }

    if (files.includes('package.json')) {
      try {
        const pkg = JSON.parse(fs.readFileSync(`${projectPath}/package.json`, 'utf8'))
        if (pkg.dependencies?.react || pkg.devDependencies?.vite) return 'React'
        return 'Node.js'
      } catch { return 'Node.js' }
    }
    if (files.includes('requirements.txt')) return 'Python'
    if (files.includes('Cargo.toml')) return 'Rust'
    if (files.includes('index.html')) return 'HTML/CSS/JS'
    if (files.some(f => f.endsWith('.py') && (f.includes('bot') || f.includes('train') || f.includes('model')))) return 'AI Project'
    if (files.includes('game.js') || files.includes('phaser.js')) return 'Game'
    if (files.includes('Makefile')) return 'C/C++'
    if (files.includes('Dockerfile')) return 'Docker'

    return 'Unknown'
  }

  /**
   * Scan important files
   */
  scanFiles(projectPath) {
    const fs = require('fs')
    const result = { source: 0, config: 0, assets: 0, total: 0 }
    try {
      for (const f of fs.readdirSync(projectPath)) {
        const full = `${projectPath}/${f}`
        if (fs.statSync(full).isDirectory()) continue
        result.total++
        if (/\.(js|ts|jsx|tsx|py|rs|c|cpp|h|html|css|scss)$/i.test(f)) result.source++
        else if (/\.(json|toml|yml|yaml|env|config)/i.test(f)) result.config++
        else result.assets++
      }
    } catch {}
    return result
  }

  /**
   * Detect git remote
   */
  detectGit(projectPath) {
    const fs = require('fs')
    const gitDir = `${projectPath}/.git`
    if (!fs.existsSync(gitDir)) return { isRepo: false, remote: '', branch: '' }
    try {
      const exec = require('child_process').execSync
      const remote = exec(`cd "${projectPath}" && git remote get-url origin 2>/dev/null`, { encoding: 'utf8' }).trim()
      const branch = exec(`cd "${projectPath}" && git rev-parse --abbrev-ref HEAD 2>/dev/null`, { encoding: 'utf8' }).trim()
      return { isRepo: true, remote, branch, commits: 0 }
    } catch { return { isRepo: true, remote: '', branch: '' } }
  }

  /**
   * Find main entry file
   */
  findEntry(projectPath, type) {
    const entries = {
      'Node.js': ['index.js', 'app.js', 'server.js', 'main.js'],
      'React': ['src/App.js', 'src/App.jsx', 'src/index.js', 'src/main.jsx'],
      'Python': ['main.py', 'bot.py', 'app.py', 'run.py'],
      'HTML/CSS/JS': ['index.html'],
      'Rust': ['src/main.rs'],
    }
    const candidates = entries[type] || ['index.html', 'main.py', 'index.js']
    for (const e of candidates) {
      try { if (require('fs').existsSync(`${projectPath}/${e}`)) return e } catch {}
    }
    return candidates[0]
  }

  /**
   * List all projects
   */
  listAll() {
    const fs = require('fs')
    const projects = []
    try {
      for (const d of fs.readdirSync(this.projectsDir)) {
        const full = `${this.projectsDir}/${d}`
        if (!fs.statSync(full).isDirectory()) continue
        projects.push(this.load(full))
      }
    } catch {}
    return projects
  }
}

window.ProjectLoader = ProjectLoader
