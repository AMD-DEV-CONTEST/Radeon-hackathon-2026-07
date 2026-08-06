import React, { useState, useEffect } from 'react';
import { LandingPage } from './components/LandingPage';
import { AuthModal } from './components/AuthModal';
import { LoginPage } from './components/LoginPage';
import { TopNav } from './components/TopNav';
import { Sidebar } from './components/Sidebar';
import { DashboardOverview } from './components/DashboardOverview';
import { DocumentsView } from './components/DocumentsView';
import { KnowledgeGraphView } from './components/KnowledgeGraphView';
import { TimelineView } from './components/TimelineView';
import { SemanticSearchView } from './components/SemanticSearchView';
import { AiChatView } from './components/AiChatView';
import { CareerInsightsView } from './components/CareerInsightsView';
import { AnalyticsView } from './components/AnalyticsView';
import { SettingsView } from './components/SettingsView';
import { DocumentDetailModal } from './components/DocumentDetailModal';
import { UploadModal } from './components/UploadModal';

import {
  DocumentItem,
  UserProfile,
  GraphNode,
  GraphLink,
  TimelineEventItem,
  CareerInsightsData,
  AppNotification,
} from './types';

import {
  initialUserProfile,
  initialDocuments,
  initialGraphNodes,
  initialGraphLinks,
  initialTimelineEvents,
  initialCareerInsights,
  initialNotifications,
} from './data/mockData';

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(true); // Default to logged in for instant view
  const [unauthView, setUnauthView] = useState<'landing' | 'login'>('landing');
  const [activeTab, setActiveTab] = useState<string>('dashboard');
  const [user, setUser] = useState<UserProfile>(initialUserProfile);

  const [documents, setDocuments] = useState<DocumentItem[]>(initialDocuments);
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>(initialGraphNodes);
  const [graphLinks, setGraphLinks] = useState<GraphLink[]>(initialGraphLinks);
  const [timelineEvents, setTimelineEvents] = useState<TimelineEventItem[]>(initialTimelineEvents);
  const [insights, setInsights] = useState<CareerInsightsData>(initialCareerInsights);
  const [notifications, setNotifications] = useState<AppNotification[]>(initialNotifications);

  const [selectedDoc, setSelectedDoc] = useState<DocumentItem | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('All');
  const [searchQuery, setSearchQuery] = useState<string>('');

  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Load initial backend state
  useEffect(() => {
    fetchDocuments();
    fetchInsights();
    fetchGraph();
    fetchTimeline();
  }, []);

  const fetchDocuments = async () => {
    try {
      const res = await fetch('/api/documents');
      const data = await res.json();
      if (data.documents && Array.isArray(data.documents)) {
        setDocuments(data.documents);
      }
    } catch (err) {
      console.warn('Backend documents fetch fallback');
    }
  };

  const fetchInsights = async () => {
    try {
      const res = await fetch('/api/insights');
      const data = await res.json();
      if (data.insights) {
        setInsights(data.insights);
      }
    } catch (err) {
      console.warn('Backend insights fetch fallback');
    }
  };

  const fetchGraph = async () => {
    try {
      const res = await fetch('/api/knowledge-graph');
      const data = await res.json();
      if (data.nodes) setGraphNodes(data.nodes);
      if (data.links) setGraphLinks(data.links);
    } catch (err) {
      console.warn('Backend graph fetch fallback');
    }
  };

  const fetchTimeline = async () => {
    try {
      const res = await fetch('/api/timeline');
      const data = await res.json();
      if (data.timeline) setTimelineEvents(data.timeline);
    } catch (err) {
      console.warn('Backend timeline fetch fallback');
    }
  };

  const handleUploadSuccess = (newDoc: DocumentItem) => {
    setDocuments((prev) => [newDoc, ...prev]);
    fetchGraph();
    fetchTimeline();

    // Add notification
    const newNotif: AppNotification = {
      id: 'notif_' + Date.now(),
      title: 'Document Uploaded & Indexed',
      message: `"${newDoc.title}" processed into ${newDoc.category} and mapped to ${newDoc.skills.length} skills.`,
      timestamp: 'Just now',
      type: 'upload',
      read: false,
    };
    setNotifications((prev) => [newNotif, ...prev]);
  };

  const handleDeleteDocument = async (docId: string) => {
    try {
      await fetch(`/api/documents/${docId}`, { method: 'DELETE' });
    } catch (err) {
      console.warn('Delete endpoint error');
    }
    setDocuments((prev) => prev.filter((d) => d.id !== docId));
    setGraphNodes((prev) => prev.filter((n) => n.docId !== docId));
    setTimelineEvents((prev) => prev.filter((t) => t.docId !== docId));
    if (selectedDoc?.id === docId) {
      setSelectedDoc(null);
    }
  };

  const handleAddSampleDoc = async (type: 'cert' | 'resume' | 'project') => {
    let sampleTitle = 'Stanford AI & Machine Learning Specialization';
    let sampleCat = 'Certificates';
    let sampleOrg = 'Stanford University';
    let sampleText =
      'Verified Stanford Online Credential in AI, Neural Networks, PyTorch, and Deep Learning.';

    if (type === 'project') {
      sampleTitle = 'LLM Vector Search & RAG Capstone Engine';
      sampleCat = 'Projects';
      sampleOrg = 'Stanford Computer Science';
      sampleText =
        'Full-stack RAG web application built with FastAPI, LangChain, React, and PostgreSQL vector similarity search.';
    } else if (type === 'resume') {
      sampleTitle = 'Alex_Morgan_AI_ML_Engineer_Resume_2026.pdf';
      sampleCat = 'Resume';
      sampleOrg = 'Personal';
      sampleText = 'Master resume highlighting Goldman Sachs internship, Stanford capstone, and AWS certification.';
    }

    try {
      const res = await fetch('/api/documents/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: sampleTitle,
          fileName: `${sampleTitle.replace(/\s+/g, '_')}.pdf`,
          fileType: 'pdf',
          category: sampleCat,
          organization: sampleOrg,
          rawText: sampleText,
        }),
      });
      const data = await res.json();
      if (data.document) {
        handleUploadSuccess(data.document);
      }
    } catch (err) {
      console.error('Failed to add sample document:', err);
    }
  };

  const handleRefreshInsights = async () => {
    try {
      const res = await fetch('/api/insights/generate', { method: 'POST' });
      const data = await res.json();
      if (data.insights) {
        setInsights(data.insights);
      }
    } catch (err) {
      console.error('Failed to generate insights:', err);
    }
  };

  const handleResetData = async () => {
    try {
      await fetch('/api/reset-sample-data', { method: 'POST' });
    } catch (err) {
      console.warn('Reset endpoint error');
    }
    setDocuments(initialDocuments);
    setGraphNodes(initialGraphNodes);
    setGraphLinks(initialGraphLinks);
    setTimelineEvents(initialTimelineEvents);
    setInsights(initialCareerInsights);
    setUser(initialUserProfile);
  };

  // Unauthenticated view flow (Landing Page or Full Login Page)
  if (!isAuthenticated) {
    if (unauthView === 'login') {
      return (
        <LoginPage
          onAuthSuccess={(u) => {
            setUser(u);
            setIsAuthenticated(true);
            setActiveTab('dashboard');
          }}
          onBackToLanding={() => setUnauthView('landing')}
        />
      );
    }

    return (
      <div className="bg-[#071326] min-h-screen">
        <LandingPage
          onGetStarted={() => setUnauthView('login')}
          onLogin={() => setUnauthView('login')}
        />
        <AuthModal
          isOpen={isAuthModalOpen}
          onClose={() => setIsAuthModalOpen(false)}
          onAuthSuccess={(u) => {
            setUser(u);
            setIsAuthenticated(true);
            setActiveTab('dashboard');
          }}
        />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#071326] text-white flex flex-col font-sans selection:bg-sky-500 selection:text-white">
      {/* Top Header */}
      <TopNav
        user={user}
        notifications={notifications}
        onOpenUpload={() => setIsUploadModalOpen(true)}
        onNavigate={(tab) => setActiveTab(tab)}
        onSearch={(q) => setSearchQuery(q)}
        onSignOut={() => {
          setIsAuthenticated(false);
          setUnauthView('login');
        }}
        onResetData={handleResetData}
        onToggleMobileMenu={() => setMobileMenuOpen(!mobileMenuOpen)}
      />

      {/* Main Body */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar */}
        <Sidebar
          activeTab={activeTab}
          user={user}
          docCount={documents.length}
          onNavigate={(tab) => setActiveTab(tab)}
          mobileOpen={mobileMenuOpen}
          onCloseMobile={() => setMobileMenuOpen(false)}
        />

        {/* Center Main View Area */}
        <main className="flex-1 overflow-y-auto bg-[#071326] pb-12">
          {activeTab === 'dashboard' && (
            <DashboardOverview
              user={user}
              documents={documents}
              insights={insights}
              onOpenUpload={() => setIsUploadModalOpen(true)}
              onNavigate={(tab) => setActiveTab(tab)}
              onSelectDocument={(doc) => setSelectedDoc(doc)}
              onDeleteDocument={handleDeleteDocument}
            />
          )}

          {activeTab === 'documents' && (
            <DocumentsView
              documents={documents}
              selectedCategory={selectedCategory}
              onSelectCategory={(cat) => setSelectedCategory(cat)}
              onOpenUpload={() => setIsUploadModalOpen(true)}
              onSelectDocument={(doc) => setSelectedDoc(doc)}
              onDeleteDocument={handleDeleteDocument}
              onAddSampleDoc={handleAddSampleDoc}
            />
          )}

          {activeTab === 'graph' && (
            <KnowledgeGraphView nodes={graphNodes} links={graphLinks} />
          )}

          {activeTab === 'timeline' && (
            <TimelineView
              events={timelineEvents}
              documents={documents}
              onSelectDocument={(doc) => setSelectedDoc(doc)}
            />
          )}

          {activeTab === 'search' && (
            <SemanticSearchView
              documents={documents}
              initialQuery={searchQuery}
              onSelectDocument={(doc) => setSelectedDoc(doc)}
            />
          )}

          {activeTab === 'chat' && (
            <AiChatView
              user={user}
              documents={documents}
              onSelectDocument={(doc) => setSelectedDoc(doc)}
            />
          )}

          {activeTab === 'insights' && (
            <CareerInsightsView
              user={user}
              insights={insights}
              onRefreshInsights={handleRefreshInsights}
            />
          )}

          {activeTab === 'analytics' && <AnalyticsView documents={documents} />}

          {activeTab === 'settings' && (
            <SettingsView
              user={user}
              documents={documents}
              onUpdateProfile={(updated) => setUser((prev) => ({ ...prev, ...updated }))}
              onResetData={handleResetData}
            />
          )}
        </main>
      </div>

      {/* Modals */}
      <DocumentDetailModal
        document={selectedDoc}
        onClose={() => setSelectedDoc(null)}
        onDelete={handleDeleteDocument}
      />

      <UploadModal
        isOpen={isUploadModalOpen}
        onClose={() => setIsUploadModalOpen(false)}
        onUploadSuccess={handleUploadSuccess}
      />
    </div>
  );
}
