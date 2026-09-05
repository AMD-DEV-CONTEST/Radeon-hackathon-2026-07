data class SearchResult(
    val filePath: String,
    val score: Double,
    val snippet: String
)

class SearchEngine {
    fun search(query: String, topK: Int): List<SearchResult> {
        return emptyList()
    }
}
