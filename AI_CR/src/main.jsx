import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { takeTokenFromUrl, watchForNewLinks } from './lib/session.js'

takeTokenFromUrl() // before the first render, so the token never stays in the address bar
watchForNewLinks()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
