import { createRoot } from 'react-dom/client'
import App from './App'

const params = new URLSearchParams(window.location.search)
const runId = params.get('run') ?? ''

createRoot(document.getElementById('root')!).render(<App runId={runId} />)
