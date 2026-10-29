/**
 * FreshRoute React entry point.
 * Responsible for: mounting <App /> and loading Leaflet + global styles.
 * NOT responsible for: layout, data fetching or map behaviour.
 */

import React from 'react'
import ReactDOM from 'react-dom/client'
import 'leaflet/dist/leaflet.css'
import './styles.css'
import App from './App.jsx'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
