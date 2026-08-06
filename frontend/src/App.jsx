import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Navbar from './components/Navbar';
import Footer from './components/Footer';
import Home from './pages/Home';
import BookList from './pages/BookList';
import BookDetails from './pages/BookDetails';
import AIChat from './pages/AIChat';
import FAQ from './pages/FAQ';
import AdminLogin from './pages/AdminLogin';
import AdminDashboard from './pages/AdminDashboard';
import AddBook from './pages/AddBook';
import EditBook from './pages/EditBook';
import Search from './pages/Search';

// Import Bootstrap dependencies
import 'bootstrap/dist/css/bootstrap.min.css';
import 'bootstrap/dist/js/bootstrap.bundle.min.js';
import 'bootstrap-icons/font/bootstrap-icons.css';

function App() {
  const [darkMode, setDarkMode] = useState(() => {
    return localStorage.getItem('theme') === 'dark';
  });

  useEffect(() => {
    if (darkMode) {
      document.body.classList.add('dark-theme');
      localStorage.setItem('theme', 'dark');
    } else {
      document.body.classList.remove('dark-theme');
      localStorage.setItem('theme', 'light');
    }
  }, [darkMode]);

  const toggleDarkMode = () => {
    setDarkMode(!darkMode);
  };

  return (
    <Router>
      <div className="d-flex flex-column min-vh-100 page-shell">
        <Navbar darkMode={darkMode} toggleDarkMode={toggleDarkMode} />
        <main className="flex-grow-1 position-relative">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/books" element={<BookList />} />
            <Route path="/books/:id" element={<BookDetails />} />
            <Route path="/search" element={<Search />} />
            <Route path="/ai-chat" element={<AIChat />} />
            <Route path="/faq" element={<FAQ />} />
            <Route path="/admin-login" element={<AdminLogin />} />
            <Route path="/admin" element={<AdminDashboard />} />
            <Route path="/admin/add-book" element={<AddBook />} />
            <Route path="/admin/edit-book/:id" element={<EditBook />} />
          </Routes>
        </main>
        <Footer />
      </div>
    </Router>
  );
}

export default App;
