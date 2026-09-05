class SearchClient {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
    }

    async search(query) {
        const response = await fetch(`${this.baseUrl}/api/search?query=${encodeURIComponent(query)}`);
        return response.json();
    }
}

const client = new SearchClient('http://localhost:8080');
document.getElementById('search-input').addEventListener('input', async (e) => {
    const results = await client.search(e.target.value);
    displayResults(results);
});
