// TypeScript interface definition
interface SearchRequest {
    query: string;
    topK: number;
    filters?: SearchFilter;
}

export class SearchService {
    async search(request: SearchRequest): Promise<SearchResult[]> {
        const response = await fetch('/api/search', {
            method: 'POST',
            body: JSON.stringify(request)
        });
        return response.json();
    }
}
