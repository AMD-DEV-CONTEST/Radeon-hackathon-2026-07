object SearchEngine {
  def search(query: String, topK: Int): List[SearchResult] = {
    val vectorStore = new VectorStore()
    vectorStore.search(query, topK)
  }
}
