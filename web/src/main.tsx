import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import '@fontsource-variable/inter'
import '@fontsource-variable/jetbrains-mono'
import App from './App'
import './index.css'

const container = document.getElementById('root')
if (container === null) {
  throw new Error('root container missing')
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
