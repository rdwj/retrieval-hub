import { Route, Routes } from 'react-router-dom';
import { Page } from '@patternfly/react-core';

import GuidedTour from './components/GuidedTour';
import Header from './components/Header';
import AdminPage from './pages/AdminPage';
import CatalogPage from './pages/CatalogPage';
import NotFoundPage from './pages/NotFoundPage';
import PlaygroundPage from './pages/PlaygroundPage';
import SourceDetailPage from './pages/SourceDetailPage';
import ValuePropPage from './pages/ValuePropPage';

export default function App() {
  return (
    <Page header={<Header />}>
      <Routes>
        <Route path="/" element={<ValuePropPage />} />
        <Route path="/catalog" element={<CatalogPage />} />
        <Route path="/sources/:slug" element={<SourceDetailPage />} />
        <Route
          path="/sources/:slug/playground"
          element={<PlaygroundPage />}
        />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
      <GuidedTour />
    </Page>
  );
}
