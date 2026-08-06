import { useAppStore } from './store/appStore'
import { LandingPage } from './pages/LandingPage'
import { DirectorPage } from './pages/DirectorPage'
import { ResultPage } from './pages/ResultPage'

function App() {
  const page = useAppStore((s) => s.page)

  return (
    <>
      {page === 'landing' && <LandingPage />}
      {page === 'director' && <DirectorPage />}
      {page === 'result' && <ResultPage />}
    </>
  )
}

export default App
