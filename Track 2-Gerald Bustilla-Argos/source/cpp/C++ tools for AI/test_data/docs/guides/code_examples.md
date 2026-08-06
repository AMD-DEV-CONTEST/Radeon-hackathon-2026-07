# Code Examples

## C++ Search Example
```cpp
VectorStore store;
store.add_chunk("authentication token");
store.finalize();
auto results = store.search("auth", 10);
```

## Python Search Example
```python
from sklearn.feature_extraction.text import TfidfVectorizer
vectorizer = TfidfVectorizer()
matrix = vectorizer.fit_transform(documents)
```
