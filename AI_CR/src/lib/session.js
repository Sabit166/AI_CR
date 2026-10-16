// The CR editor has no sign-in. /manage in Discord sends the CR a private link
// like /cr/#t=<token>; the token names the class and expires after a few hours.
// It is read from the URL fragment (never sent to a server by the browser), kept
// for this tab only, and removed from the address bar so it isn't copied along
// with the page URL or left in history.
const KEY = 'aicr-editor-token'
let memoryToken = null // when sessionStorage is blocked

function fromHash() {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  return params.get('t')
}

export function takeTokenFromUrl() {
  const token = fromHash()
  if (!token) return false
  try {
    sessionStorage.setItem(KEY, token)
  } catch {
    memoryToken = token
  }
  window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}#exams`)
  return true
}

// A new /manage link opened in a tab that already shows the editor only changes the
// fragment, which doesn't reload the page: take the new token and start over.
export function watchForNewLinks() {
  window.addEventListener('hashchange', () => {
    if (takeTokenFromUrl()) window.location.reload()
  })
}

export function editorToken() {
  try {
    return sessionStorage.getItem(KEY) ?? memoryToken
  } catch {
    return memoryToken
  }
}

export function forgetToken() {
  memoryToken = null
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    // storage blocked: nothing was stored
  }
}
