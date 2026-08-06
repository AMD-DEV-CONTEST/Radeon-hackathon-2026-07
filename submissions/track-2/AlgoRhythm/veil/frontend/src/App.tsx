import { AppProvider, useApp } from '@/context/AppContext'
import { AppShell } from '@/components/layout/AppShell'
import { LoginScreen } from '@/components/auth/LoginScreen'
import { OverviewPage } from '@/pages/Overview'
import { DocumentsPage } from '@/pages/Documents'
import { AuditWorkspacePage } from '@/pages/AuditWorkspace'
import { ActivityPage } from '@/pages/Activity'
import { SecurityPage } from '@/pages/Security'
import { AnimatePresence, motion } from 'framer-motion'

function PageRouter() {
  const { auth, currentPage } = useApp()

  if (!auth) {
    return <LoginScreen />
  }

  const pageMap = {
    overview:  <OverviewPage />,
    documents: <DocumentsPage />,
    audit:     <AuditWorkspacePage />,
    activity:  <ActivityPage />,
    security:  <SecurityPage />,
  }

  return (
    <AppShell>
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={currentPage}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.12 }}
          className="h-full"
        >
          {pageMap[currentPage] ?? <OverviewPage />}
        </motion.div>
      </AnimatePresence>
    </AppShell>
  )
}

export default function App() {
  return (
    <AppProvider>
      <PageRouter />
    </AppProvider>
  )
}
