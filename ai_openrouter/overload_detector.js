/**
 * overload_detector.js
 * Detects provider overload conditions from API responses.
 * Triggers instant model switch on busy/overloaded.
 */

const OVERLOAD_PATTERNS = [
  'service is too busy',
  'too busy',
  'overloaded',
  'capacity exceeded',
  'provider unavailable',
  'upstream timeout',
  'upstream error',
  'service unavailable',
  'temporarily unavailable',
  '503',
  '502',
  'too many requests',
  'rate limit exceeded',
  'please try again later',
  'server busy',
  'high demand',
  'no available',
  'all servers are busy',
  'overloaded. try again',
  'currently unable',
]

function isOverloaded(responseBody, statusCode) {
  if (statusCode === 503 || statusCode === 502) return true
  if (!responseBody) return false
  const body = typeof responseBody === 'string' ? responseBody.toLowerCase() : JSON.stringify(responseBody).toLowerCase()
  for (const p of OVERLOAD_PATTERNS) {
    if (body.includes(p)) return true
  }
  return false
}

function detectErrorType(responseBody, statusCode) {
  if (isOverloaded(responseBody, statusCode)) return 'overloaded'
  if (statusCode === 429) return 'rate_limited'
  if (statusCode === 404) return 'not_found'
  if (statusCode === 0 || !statusCode) return 'timeout'
  if (statusCode >= 500) return 'overloaded'
  return 'error'
}

window.OverloadDetector = { isOverloaded, detectErrorType }
