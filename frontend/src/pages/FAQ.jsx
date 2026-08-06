import React from 'react';

const FAQ = () => {
  const faqs = [
    {
      id: 'collapseOne',
      question: '🕒 What are the library operating hours?',
      answer: 'Our library is open Monday through Friday from 8:00 AM to 8:00 PM, and Saturdays from 9:00 AM to 5:00 PM. We are closed on Sundays and public holidays.'
    },
    {
      id: 'collapseTwo',
      question: '📚 What is the maximum number of books I can borrow?',
      answer: 'Students can borrow up to 5 books at any given time. Faculty members are permitted to borrow up to 10 books simultaneously.'
    },
    {
      id: 'collapseThree',
      question: '⏳ What is the borrow duration for books?',
      answer: 'Books can be borrowed for a period of 14 days (2 weeks). If you need the books for longer, you can renew them online or at the help desk before the due date, provided another student hasn\'t reserved them.'
    },
    {
      id: 'collapseFour',
      question: '💰 What is the library late return fine policy?',
      answer: 'To ensure all students get access to books, we charge a late fee of $0.50 per day for each overdue book. Fines can be paid at the main counter or through your student account portal.'
    },
    {
      id: 'collapseFive',
      question: '🏛️ What are the general library conduct rules?',
      answer: 'We maintain silent study zones where talking is strictly prohibited. Food is not allowed inside the library to protect books and facilities. However, you are permitted to bring covered drinks (like bottles with caps). Always carry your Student ID card as it is required for entry and self-checkout.'
    },
    {
      id: 'collapseSix',
      question: '📞 How can I contact the library staff?',
      answer: 'You can email our support team at support@library.edu or call the help desk at +1-555-0199. We are located in the Central Campus, Building B. Our librarians are always available to help you locate resources!'
    }
  ];

  return (
    <div className="container py-5 position-relative fade-in" style={{ minHeight: '80vh' }}>
      <div className="orb orb-1"></div>
      <div className="orb orb-2"></div>

      <div className="row justify-content-center">
        <div className="col-lg-8">
          <div className="text-center mb-5">
            <div className="section-chip mb-3">Helpful answers</div>
            <h1 className="fw-extrabold heading-font display-6 mb-2">Library FAQs</h1>
            <p className="text-muted">Quick answers to common questions about library access, borrowing, and support.</p>
          </div>

          <div className="accordion accordion-flush d-flex flex-column gap-3" id="faqAccordion">
            {faqs.map((faq, idx) => (
              <div key={idx} className="accordion-item glass-card border-0 overflow-hidden rounded-4 shadow-sm">
                <h2 className="accordion-header" id={`heading${faq.id}`}>
                  <button
                    className="accordion-button collapsed bg-transparent fw-bold py-3 px-4"
                    type="button"
                    data-bs-toggle="collapse"
                    data-bs-target={`#${faq.id}`}
                    aria-expanded="false"
                    aria-controls={faq.id}
                    style={{ color: 'var(--text-color)', boxShadow: 'none' }}
                  >
                    <span>{faq.question}</span>
                  </button>
                </h2>
                <div
                  id={faq.id}
                  className="accordion-collapse collapse"
                  aria-labelledby={`heading${faq.id}`}
                  data-bs-parent="#faqAccordion"
                >
                  <div className="accordion-body px-4 pb-4 pt-1 text-muted lh-lg" style={{ fontSize: '0.95rem' }}>
                    {faq.answer}
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="glass-card p-4 border-0 rounded-4 text-center mt-5 shadow-sm">
            <h5 className="fw-bold heading-font mb-2">Need more help?</h5>
            <p className="text-muted mb-3" style={{ fontSize: '0.95rem' }}>Chat with the AI assistant for a faster answer about books, shelving, or library rules.</p>
            <Link to="/ai-chat" className="btn btn-primary rounded-pill px-4">
              Ask AI assistant
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
};

export default FAQ;
