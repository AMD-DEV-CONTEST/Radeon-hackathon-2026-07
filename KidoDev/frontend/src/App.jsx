import React, { lazy, Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Navbar from './components/Navbar';
import ScrollToTop from './components/ScrollToTop';
import Footer from './components/Footer';
import ErrorBoundary from './components/ErrorBoundary';
import ProtectedRoute from './components/ProtectedRoute';
import SpriteLoader from './components/Loader/SpriteLoader';
import { ThemeProvider } from './utils/ThemeContext';

// Lazy-loaded pages for optimal bundle size & initial load speed
const Home = lazy(() => import('./pages/Home'));
const Auth = lazy(() => import('./pages/Auth/index'));
const Levels = lazy(() => import('./pages/Levels'));
const MagicStudio = lazy(() => import('./pages/MagicStudio/index'));
const AdminDashboard = lazy(() => import('./pages/Admin/AdminDashboard'));
const ParentDashboard = lazy(() => import('./pages/Auth/ParentDashboard/ParentDashboard'));
const SchoolDashboard = lazy(() => import('./pages/Auth/SchoolDashboard/SchoolDashboard'));
const PaymentRegistration = lazy(() => import('./pages/PaymentRegistration'));
const GamesHub = lazy(() => import('./pages/Games/GamesHub'));
const AudioProvider = lazy(() => import('./pages/Games/AudioProvider'));
const AboutUs = lazy(() => import('./pages/Info/AboutUs'));
const HowToUse = lazy(() => import('./pages/Info/HowToUse'));
const Pricing = lazy(() => import('./pages/Info/Pricing'));
const PrivacyPolicy = lazy(() => import('./pages/Info/PrivacyPolicy'));
const PersonalizedPath = lazy(() => import('./pages/PersonalizedPath'));

function App() {
  return (
    <ThemeProvider>
      <Router>
        <ScrollToTop />
        <Suspense fallback={<SpriteLoader />}>
          <Routes>
            {/* Studio is full-screen – no Navbar/Footer – wrapped in ErrorBoundary */}
            <Route path="/studio/:lessonId" element={
              <ProtectedRoute>
                <ErrorBoundary>
                  <MagicStudio />
                </ErrorBoundary>
              </ProtectedRoute>
            } />

            {/* Normal pages with Navbar + Footer */}
            <Route path="/*" element={
              <div className="app-container" style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
                <Navbar />
                <div className="main-content-wrapper" style={{ flex: 1, position: 'relative', display: 'flex', flexDirection: 'column' }}>
                  <ErrorBoundary>
                    <Routes>
                      <Route path="/" element={<Home />} />
                      <Route path="/auth" element={<Auth />} />
                      <Route path="/register" element={<PaymentRegistration />} />
                      <Route path="/about-us" element={<AboutUs />} />
                      <Route path="/how-to-use" element={<HowToUse />} />
                      <Route path="/pricing" element={<Pricing />} />
                      <Route path="/privacy-policy" element={<PrivacyPolicy />} />

                      <Route path="/levels" element={
                        <ProtectedRoute>
                          <AudioProvider>
                            <Levels />
                          </AudioProvider>
                        </ProtectedRoute>
                      } />
                      <Route path="/games" element={
                        <ProtectedRoute>
                          <AudioProvider>
                            <GamesHub />
                          </AudioProvider>
                        </ProtectedRoute>
                      } />
                      <Route path="/parent-dashboard" element={
                        <ProtectedRoute>
                          <ParentDashboard />
                        </ProtectedRoute>
                      } />
                      <Route path="/school-dashboard" element={
                        <ProtectedRoute>
                          <SchoolDashboard />
                        </ProtectedRoute>
                      } />
                      <Route path="/admin" element={<AdminDashboard />} />
                      <Route path="/my-path" element={
                        <ProtectedRoute>
                          <PersonalizedPath />
                        </ProtectedRoute>
                      } />
                    </Routes>
                  </ErrorBoundary>
                </div>
                <Footer />
              </div>
            } />
          </Routes>
        </Suspense>
      </Router>
    </ThemeProvider>
  );
}

export default App;
