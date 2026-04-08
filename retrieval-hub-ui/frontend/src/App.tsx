import { Navigate, Route, Routes } from 'react-router-dom';
import { Page } from '@patternfly/react-core';

import Header from './components/Header';
import CatalogPage from './pages/CatalogPage';
import SourceDetailPage from './pages/SourceDetailPage';
import AdminPage from './pages/AdminPage';
import PlaygroundPage from './pages/PlaygroundPage';
import NotFoundPage from './pages/NotFoundPage';

export default function App() {
  return (
    <Page header={<Header />}>
      <Routes>
        <Route path="/" element={<Navigate to="/catalog" replace />} />
        <Route path="/catalog" element={<CatalogPage />} />
        <Route path="/sources/:slug" element={<SourceDetailPage />} />
        <Route
          path="/sources/:slug/playground"
          element={<PlaygroundPage />}
        />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Page>
  );
}
