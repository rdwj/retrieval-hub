import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import '@patternfly/react-core/dist/styles/base.css';

import App from './App';
import { PersonaProvider } from './context/PersonaContext';
import { TourProvider } from './context/TourContext';

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <PersonaProvider>
        <TourProvider>
          <App />
        </TourProvider>
      </PersonaProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
