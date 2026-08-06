import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import App from './App.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <BrowserRouter>
    <App />
    <Toaster
      position="top-right"
      toastOptions={{
        style: {
          background: '#FFFDF9',
          color: '#223A5E',
          border: '1px solid rgba(118,96,78,0.16)',
          borderRadius: '12px',
          fontSize: '0.875rem',
          boxShadow: '0 12px 30px rgba(67,48,35,0.12)',
        },
        success: { iconTheme: { primary: '#6F9B73', secondary: '#FFFDF9' } },
        error:   { iconTheme: { primary: '#B8625A', secondary: '#FFFDF9' } },
      }}
    />
  </BrowserRouter>
)
