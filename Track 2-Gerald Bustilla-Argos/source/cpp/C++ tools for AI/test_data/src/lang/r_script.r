search_tfidf <- function(query, documents, top_k=10) {
  tfidf <- TFIDF$new(documents)
  scores <- tfidf$cosine_similarity(query)
  ranked <- order(scores, decreasing=TRUE)[1:top_k]
  return(ranked)
}
