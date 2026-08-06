-- Seed Data for Books
INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(1, 'Effective Java', 'Joshua Bloch', 'Java', 'The definitive guide to Java platform best practices, updated for Java 9, 11, and beyond.', 'Addison-Wesley', '978-0134685991', 'A-101', 5, true, 'https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(2, 'Clean Code', 'Robert C. Martin', 'Software Engineering', 'A handbook of agile software craftsmanship that teaches you how to write good code and transform bad code.', 'Prentice Hall', '978-0132350884', 'SE-201', 4, true, 'https://images.unsplash.com/photo-1512820790803-83ca734da794?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(3, 'Clean Architecture', 'Robert C. Martin', 'Software Engineering', 'A craftsman guide to software structure and design, presenting the universal rules of software architecture.', 'Prentice Hall', '978-0134494166', 'SE-202', 3, true, 'https://images.unsplash.com/photo-1629654297299-c8506221ca97?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(4, 'Java: The Complete Reference', 'Herbert Schildt', 'Java', 'A comprehensive guide to the Java programming language, covering syntax, keywords, and fundamental principles.', 'McGraw Hill', '978-1260440232', 'A-102', 6, true, 'https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(5, 'Head First Java', 'Kathy Sierra, Bert Bates', 'Java', 'A learner-friendly guide to Java and object-oriented programming, packed with visually rich puzzles and interviews.', 'O\'Reilly', '978-1492091622', 'A-103', 0, false, 'https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(6, 'Spring in Action', 'Craig Walls', 'Backend', 'A comprehensive hands-on guide that takes you from building simple Web applications to microservices with Spring.', 'Manning', '978-1617294945', 'B-101', 3, true, 'https://images.unsplash.com/photo-1589829545856-d10d557cf95f?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(7, 'Designing Data-Intensive Applications', 'Martin Kleppmann', 'Database', 'An expert guide to the systems, architectures, and algorithms that power modern, scalable applications.', 'O\'Reilly', '978-1449373320', 'DB-301', 4, true, 'https://images.unsplash.com/photo-1544383835-bda2bc66a55d?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(8, 'Database System Concepts', 'Abraham Silberschatz', 'Database', 'The classic textbook presenting the fundamental concepts of database management and SQL systems.', 'McGraw Hill', '978-0078022159', 'DB-302', 2, true, 'https://images.unsplash.com/photo-1544383835-bda2bc66a55d?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(9, 'Python Crash Course', 'Eric Matthes', 'Python', 'A fast-paced, thorough introduction to Python programming that will have you writing programs and solving problems.', 'No Starch Press', '978-1593279288', 'P-401', 5, true, 'https://images.unsplash.com/photo-1515879218367-8466d910aaa4?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(10, 'Fluent Python', 'Luciano Ramalho', 'Python', 'A detailed guide to writing professional, idiomatic Python code by utilizing its best features.', 'O\'Reilly', '978-1491946008', 'P-402', 3, true, 'https://images.unsplash.com/photo-1515879218367-8466d910aaa4?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(11, 'Eloquent JavaScript', 'Marijn Haverbeke', 'Frontend', 'A modern introduction to programming, JavaScript, and browsers, utilizing code examples and projects.', 'No Starch Press', '978-1593279509', 'F-501', 4, true, 'https://images.unsplash.com/photo-1507721999472-8ed4421c4b2e?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(12, 'You Don\'t Know JS Yet: Get Started', 'Kyle Simpson', 'Frontend', 'Part of the respected book series diving deep into the core mechanisms of the JavaScript language.', 'Independently Published', '978-1082390623', 'F-502', 7, true, 'https://images.unsplash.com/photo-1507721999472-8ed4421c4b2e?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(13, 'Artificial Intelligence: A Modern Approach', 'Stuart Russell, Peter Norvig', 'AI', 'The long-standing standard textbook in AI, offering a comprehensive, state-of-the-art introduction.', 'Pearson', '978-0134610993', 'AI-601', 2, true, 'https://images.unsplash.com/photo-1677442136019-21780efad99a?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(14, 'Introduction to Machine Learning with Python', 'Andreas C. Müller, Sarah Guido', 'Machine Learning', 'A practical guide to building machine learning models using Python and the scikit-learn library.', 'O\'Reilly', '978-1449369415', 'ML-701', 3, true, 'https://images.unsplash.com/photo-1527474305487-b87b222841cc?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(15, 'Hands-On Machine Learning', 'Aurélien Géron', 'Machine Learning', 'A comprehensive reference for machine learning and deep learning using Scikit-Learn, Keras, and TensorFlow.', 'O\'Reilly', '978-1492032649', 'ML-702', 4, true, 'https://images.unsplash.com/photo-1527474305487-b87b222841cc?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(16, 'Computer Networks', 'Andrew S. Tanenbaum', 'Networking', 'The classic guide to computer networking, describing structure, protocols, and architectural models.', 'Pearson', '978-0132126953', 'NW-801', 3, true, 'https://images.unsplash.com/photo-1544256718-3bcf237f3974?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(17, 'Operating System Concepts', 'Abraham Silberschatz', 'Operating Systems', 'A standard introduction to operating systems, presenting basic concepts like processes, threads, and memory.', 'Wiley', '978-1118063330', 'OS-901', 2, true, 'https://images.unsplash.com/photo-1607799279861-4dd421887fb3?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(18, 'Refactoring: Improving the Design of Existing Code', 'Martin Fowler', 'Software Engineering', 'Fowler\'s landmark guide to restructuring code without changing its external behavior.', 'Addison-Wesley', '978-0134757599', 'SE-203', 3, true, 'https://images.unsplash.com/photo-1629654297299-c8506221ca97?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(19, 'Design Patterns', 'Erich Gamma, Richard Helm, Ralph Johnson, John Vlissides', 'Software Engineering', 'The seminal book on design patterns, describing 23 reusable solutions to common software design problems.', 'Addison-Wesley', '978-0201633610', 'SE-204', 5, true, 'https://images.unsplash.com/photo-1629654297299-c8506221ca97?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(20, 'Grokking Algorithms', 'Aditya Bhargava', 'Software Engineering', 'An illustrated, friendly guide to algorithms, data structures, and practical coding exercises.', 'Manning', '978-1617292231', 'SE-205', 6, true, 'https://images.unsplash.com/photo-1618401471353-b98aedd07871?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(21, 'Introduction to Algorithms', 'Thomas H. Cormen, Charles E. Leiserson, Ronald L. Rivest, Clifford Stein', 'Software Engineering', 'The definitive, highly comprehensive textbook on data structures and algorithm analysis.', 'MIT Press', '978-0262046305', 'SE-206', 2, true, 'https://images.unsplash.com/photo-1618401471353-b98aedd07871?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(22, 'The Pragmatic Programmer', 'David Thomas, Andrew Hunt', 'Software Engineering', 'One of the most significant books on software development, covering developer mindset, tooling, and career paths.', 'Addison-Wesley', '978-0135957059', 'SE-207', 4, true, 'https://images.unsplash.com/photo-1515879218367-8466d910aaa4?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(23, 'Modern Operating Systems', 'Andrew S. Tanenbaum, Herbert Bos', 'Operating Systems', 'A clear, detailed explanation of operating systems design, including security, virtualization, and file systems.', 'Pearson', '978-0133591620', 'OS-902', 3, true, 'https://images.unsplash.com/photo-1607799279861-4dd421887fb3?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(24, 'High Performance MySQL', 'Silvia Botros, Jeremy Tinley', 'Database', 'A deep dive into indexing, query optimization, security, replication, and high availability features of MySQL.', 'O\'Reilly', '978-1492080534', 'DB-303', 4, true, 'https://images.unsplash.com/photo-1544383835-bda2bc66a55d?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(25, 'SQL Practice Problems', 'Sylvia Moestl Vasilik', 'Database', 'A practical guide designed to help developers solve real-world SQL query problems and learn database optimization.', 'Independently Published', '978-1541051515', 'DB-304', 5, true, 'https://images.unsplash.com/photo-1544383835-bda2bc66a55d?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(26, 'Microservices Patterns', 'Chris Richardson', 'Backend', 'A guide to designing, building, and deploying scalable microservices applications using Spring Boot.', 'Manning', '978-1617294549', 'B-102', 3, true, 'https://images.unsplash.com/photo-1589829545856-d10d557cf95f?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(27, 'Deep Learning', 'Ian Goodfellow, Yoshua Bengio, Aaron Courville', 'AI', 'The definitive textbook on deep learning, written by leading researchers in the field of Artificial Intelligence.', 'MIT Press', '978-0262035613', 'AI-602', 2, true, 'https://images.unsplash.com/photo-1677442136019-21780efad99a?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(28, 'Python Data Science Handbook', 'Jake VanderPlas', 'Python', 'A detailed reference guide to Pandas, NumPy, Scikit-Learn, and other data analysis libraries in Python.', 'O\'Reilly', '978-1491912058', 'P-403', 4, true, 'https://images.unsplash.com/photo-1515879218367-8466d910aaa4?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(29, 'React Key Concepts', 'Maximilian Schwarzmüller', 'Frontend', 'Build modern frontend interfaces with React, including state management, hooks, and routing.', 'Packt Publishing', '978-1803233543', 'F-503', 5, true, 'https://images.unsplash.com/photo-1507721999472-8ed4421c4b2e?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;

INSERT INTO books (id, title, author, category, description, publisher, isbn, shelf_number, quantity, availability, image_url, created_at, updated_at) VALUES
(30, 'Computer Networking: A Top-Down Approach', 'James Kurose, Keith Ross', 'Networking', 'An engaging introduction to computer networking principles from the application layer down to the physical layer.', 'Pearson', '978-0133594140', 'NW-802', 3, true, 'https://images.unsplash.com/photo-1544256718-3bcf237f3974?q=80&w=300', NOW(), NOW())
ON DUPLICATE KEY UPDATE id=id;
