// Neo4j Movie Graph Test Data
// Based on the classic Neo4j movie database example

// === People (Actors, Directors, Producers) ===
CREATE (keanu:Person {name: 'Keanu Reeves', born: 1964})
CREATE (carrie:Person {name: 'Carrie-Anne Moss', born: 1967})
CREATE (laurence:Person {name: 'Laurence Fishburne', born: 1961})
CREATE (hugo:Person {name: 'Hugo Weaving', born: 1960})
CREATE (lillyW:Person {name: 'Lilly Wachowski', born: 1967})
CREATE (lanaW:Person {name: 'Lana Wachowski', born: 1965})
CREATE (joelS:Person {name: 'Joel Silver', born: 1952})

CREATE (tomH:Person {name: 'Tom Hanks', born: 1956})
CREATE (robinW:Person {name: 'Robin Wright', born: 1966})
CREATE (garyS:Person {name: 'Gary Sinise', born: 1955})
CREATE (sallyF:Person {name: 'Sally Field', born: 1946})
CREATE (robertZ:Person {name: 'Robert Zemeckis', born: 1952})

CREATE (marlonB:Person {name: 'Marlon Brando', born: 1924})
CREATE (alP:Person {name: 'Al Pacino', born: 1940})
CREATE (jamesC:Person {name: 'James Caan', born: 1940})
CREATE (robertD:Person {name: 'Robert De Niro', born: 1943})
CREATE (francisC:Person {name: 'Francis Ford Coppola', born: 1939})

CREATE (leonardoD:Person {name: 'Leonardo DiCaprio', born: 1974})
CREATE (josephGL:Person {name: 'Joseph Gordon-Levitt', born: 1981})
CREATE (ellenP:Person {name: 'Elliot Page', born: 1987})
CREATE (marionC:Person {name: 'Marion Cotillard', born: 1975})
CREATE (christopherN:Person {name: 'Christopher Nolan', born: 1970})

CREATE (mattD:Person {name: 'Matt Damon', born: 1970})
CREATE (jessicaC:Person {name: 'Jessica Chastain', born: 1977})
CREATE (anneH:Person {name: 'Anne Hathaway', born: 1982})
CREATE (michaelC:Person {name: 'Michael Caine', born: 1933})

// === Movies ===
CREATE (matrix:Movie {title: 'The Matrix', tagline: 'Welcome to the Real World', released: 1999})
CREATE (matrixReloaded:Movie {title: 'The Matrix Reloaded', tagline: 'Free your mind', released: 2003})
CREATE (matrixRevolutions:Movie {title: 'The Matrix Revolutions', tagline: 'Everything that has a beginning has an end', released: 2003})

CREATE (forrestGump:Movie {title: 'Forrest Gump', tagline: 'Life is like a box of chocolates', released: 1994})
CREATE (castAway:Movie {title: 'Cast Away', tagline: 'At the edge of the world, his journey begins', released: 2000})

CREATE (godfather:Movie {title: 'The Godfather', tagline: "An offer you can't refuse", released: 1972})
CREATE (godfather2:Movie {title: 'The Godfather Part II', tagline: 'All the power on earth can not change destiny', released: 1974})

CREATE (inception:Movie {title: 'Inception', tagline: 'Your mind is the scene of the crime', released: 2010})
CREATE (interstellar:Movie {title: 'Interstellar', tagline: 'Mankind was born on Earth. It was never meant to die here', released: 2014})

// === Relationships ===
// Matrix series
CREATE (keanu)-[:ACTED_IN {roles: ['Neo']}]->(matrix)
CREATE (carrie)-[:ACTED_IN {roles: ['Trinity']}]->(matrix)
CREATE (laurence)-[:ACTED_IN {roles: ['Morpheus']}]->(matrix)
CREATE (hugo)-[:ACTED_IN {roles: ['Agent Smith']}]->(matrix)
CREATE (lillyW)-[:DIRECTED]->(matrix)
CREATE (lanaW)-[:DIRECTED]->(matrix)
CREATE (joelS)-[:PRODUCED]->(matrix)

CREATE (keanu)-[:ACTED_IN {roles: ['Neo']}]->(matrixReloaded)
CREATE (carrie)-[:ACTED_IN {roles: ['Trinity']}]->(matrixReloaded)
CREATE (laurence)-[:ACTED_IN {roles: ['Morpheus']}]->(matrixReloaded)
CREATE (hugo)-[:ACTED_IN {roles: ['Agent Smith']}]->(matrixReloaded)
CREATE (lillyW)-[:DIRECTED]->(matrixReloaded)
CREATE (lanaW)-[:DIRECTED]->(matrixReloaded)
CREATE (joelS)-[:PRODUCED]->(matrixReloaded)

CREATE (keanu)-[:ACTED_IN {roles: ['Neo']}]->(matrixRevolutions)
CREATE (carrie)-[:ACTED_IN {roles: ['Trinity']}]->(matrixRevolutions)
CREATE (laurence)-[:ACTED_IN {roles: ['Morpheus']}]->(matrixRevolutions)
CREATE (hugo)-[:ACTED_IN {roles: ['Agent Smith']}]->(matrixRevolutions)
CREATE (lillyW)-[:DIRECTED]->(matrixRevolutions)
CREATE (lanaW)-[:DIRECTED]->(matrixRevolutions)
CREATE (joelS)-[:PRODUCED]->(matrixRevolutions)

// Forrest Gump
CREATE (tomH)-[:ACTED_IN {roles: ['Forrest Gump']}]->(forrestGump)
CREATE (robinW)-[:ACTED_IN {roles: ['Jenny Curran']}]->(forrestGump)
CREATE (garyS)-[:ACTED_IN {roles: ['Lieutenant Dan Taylor']}]->(forrestGump)
CREATE (sallyF)-[:ACTED_IN {roles: ['Mrs. Gump']}]->(forrestGump)
CREATE (robertZ)-[:DIRECTED]->(forrestGump)

// Cast Away (Tom Hanks + Robert Zemeckis connection)
CREATE (tomH)-[:ACTED_IN {roles: ['Chuck Noland']}]->(castAway)
CREATE (robertZ)-[:DIRECTED]->(castAway)

// The Godfather
CREATE (marlonB)-[:ACTED_IN {roles: ['Don Vito Corleone']}]->(godfather)
CREATE (alP)-[:ACTED_IN {roles: ['Michael Corleone']}]->(godfather)
CREATE (jamesC)-[:ACTED_IN {roles: ['Sonny Corleone']}]->(godfather)
CREATE (francisC)-[:DIRECTED]->(godfather)

CREATE (alP)-[:ACTED_IN {roles: ['Michael Corleone']}]->(godfather2)
CREATE (robertD)-[:ACTED_IN {roles: ['Vito Corleone']}]->(godfather2)
CREATE (francisC)-[:DIRECTED]->(godfather2)

// Inception
CREATE (leonardoD)-[:ACTED_IN {roles: ['Cobb']}]->(inception)
CREATE (josephGL)-[:ACTED_IN {roles: ['Arthur']}]->(inception)
CREATE (ellenP)-[:ACTED_IN {roles: ['Ariadne']}]->(inception)
CREATE (marionC)-[:ACTED_IN {roles: ['Mal']}]->(inception)
CREATE (michaelC)-[:ACTED_IN {roles: ['Miles']}]->(inception)
CREATE (christopherN)-[:DIRECTED]->(inception)

// Interstellar
CREATE (mattD)-[:ACTED_IN {roles: ['Cooper']}]->(interstellar)
CREATE (jessicaC)-[:ACTED_IN {roles: ['Murph']}]->(interstellar)
CREATE (anneH)-[:ACTED_IN {roles: ['Brand']}]->(interstellar)
CREATE (michaelC)-[:ACTED_IN {roles: ['Professor Brand']}]->(interstellar)
CREATE (christopherN)-[:DIRECTED]->(interstellar)
