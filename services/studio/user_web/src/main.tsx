import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Desktop shell (pywebview) hands off the Studio session token via the
// URL fragment: https://studio.laborster.com/#token=...&machine=...
// Fragment (not querystring) keeps it out of access logs and Referer
// headers; we scrub it immediately so the secret doesn't live in
// session history. Persist before React mounts so the auth context
// loads straight into the logged-in tree.
if (window.location.hash.startsWith('#token=')) {
  const params = new URLSearchParams(window.location.hash.slice(1))
  const token = params.get('token')
  if (token) localStorage.setItem('laborster-studio-token', token)
  history.replaceState(null, '', window.location.pathname + window.location.search)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
