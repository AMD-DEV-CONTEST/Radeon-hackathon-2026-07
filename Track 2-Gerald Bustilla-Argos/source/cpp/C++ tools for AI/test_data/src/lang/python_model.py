import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

class SearchModel:
    def __init__(self):
        self.vectorizer = TfidfVectorizer(
            max_features=10000,
            stop_words='english'
        )
    
    def fit(self, documents):
        self.tfidf_matrix = self.vectorizer.fit_transform(documents)
    
    def search(self, query, top_k=10):
        query_vec = self.vectorizer.transform([query])
        scores = (self.tfidf_matrix @ query_vec.T).toarray().flatten()
        top_indices = np.argsort(scores)[-top_k:][::-1]
        return top_indices, scores[top_indices]
