import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '../index.css'
import '../App.css'
import './student.css'
import StudentApp from './StudentApp.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <StudentApp />
  </StrictMode>,
)
