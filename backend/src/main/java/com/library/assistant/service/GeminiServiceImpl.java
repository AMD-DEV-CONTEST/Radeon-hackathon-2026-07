package com.library.assistant.service;

import com.library.assistant.dto.BookDTO;
import com.library.assistant.dto.ChatResponseDTO;
import com.library.assistant.entity.Book;
import com.library.assistant.repository.BookRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.*;
import java.util.stream.Collectors;

@Service
public class GeminiServiceImpl implements GeminiService {

    private final BookRepository bookRepository;
    private final RestTemplate restTemplate;

    @Value("${gemini.api.key:}")
    private String apiKey;

    @Value("${gemini.model:gemini-1.5-flash}")
    private String modelName;

    @Value("${gemini.api.url:https://generativelanguage.googleapis.com/v1beta/models}")
    private String apiUrl;

    @Autowired
    public GeminiServiceImpl(BookRepository bookRepository) {
        this.bookRepository = bookRepository;
        this.restTemplate = new RestTemplate();
    }

    @Override
    public ChatResponseDTO generateResponse(String question) {
        // 1. Extract keywords and fetch matching available books from MySQL
         System.out.println("===== GEMINI DEBUG =====");
    System.out.println("API KEY = " + apiKey);
        Set<String> keywords = extractKeywords(question);
        List<Book> matchingBooks = new ArrayList<>();

        if (!keywords.isEmpty()) {
            Map<Long, Book> uniqueBooks = new HashMap<>();
            for (String keyword : keywords) {
                List<Book> found = bookRepository.searchAvailableBooks(keyword);
                for (Book b : found) {
                    uniqueBooks.put(b.getId(), b);
                }
            }
            matchingBooks.addAll(uniqueBooks.values());
        }

        // Convert matching books to DTOs for frontend use
        List<BookDTO> recommendedBooks = matchingBooks.stream()
                .map(this::convertToDTO)
                .collect(Collectors.toList());

        // 2. Build the detailed context prompt
        String prompt = buildPrompt(question, matchingBooks);

        // 3. Check if Gemini API key is configured
        if (apiKey == null || apiKey.trim().isEmpty() || apiKey.equals("${GEMINI_API_KEY}")) {
            return buildOfflineResponse(question, recommendedBooks);
        }

        try {
            // 4. Call Gemini API
            String responseText = callGeminiAPI(prompt);
            return ChatResponseDTO.builder()
                    .response(responseText)
                    .recommendedBooks(recommendedBooks)
                    .build();
        } catch (Exception e) {
            // Log the exception and return a friendly error response with the MySQL matches
            System.err.println("Error calling Gemini API: " + e.getMessage());
            return buildErrorResponse(e.getMessage(), recommendedBooks);
        }
    }

    private String buildPrompt(String question, List<Book> books) {
        StringBuilder bookListStr = new StringBuilder();
        if (books.isEmpty()) {
            bookListStr.append("No books found matching this request in the library catalog.\n");
        } else {
            for (Book book : books) {
                bookListStr.append(String.format("- ID: %d | Title: '%s' | Author: '%s' | Category: '%s' | Description: '%s' | Shelf: '%s' | Quantity Available: %d\n",
                        book.getId(), book.getTitle(), book.getAuthor(), book.getCategory(), book.getDescription(), book.getShelfNumber(), book.getQuantity()));
            }
        }

        return "You are an intelligent digital library assistant for the University Library. " +
                "Your job is to assist students with their questions about books and library policies.\n\n" +
                "LIBRARY FAQ & POLICIES:\n" +
                "- Timings: Monday to Friday: 8:00 AM - 8:00 PM, Saturday: 9:00 AM - 5:00 PM, Sunday: Closed.\n" +
                "- Max books allowed: 5 books for students, 10 books for faculty.\n" +
                "- Borrow duration: 14 days (2 weeks) for students.\n" +
                "- Fine policy: $0.50 per day per book for late returns.\n" +
                "- Contact details: Email: support@library.edu, Phone: +1-555-0199, Location: Central Campus, Building B.\n" +
                "- Library rules: Maintain silence in study zones. No food is allowed inside the library. Covered drinks are permitted. Student ID card is mandatory for entry and issuing books.\n\n" +
                "AVAILABLE BOOKS IN DATABASE:\n" +
                bookListStr.toString() + "\n" +
                "INSTRUCTIONS:\n" +
                "1. Answer the student's question politely, naturally, and professionally.\n" +
                "2. If the student asks for book recommendations, suggestions, or searches, recommend books ONLY from the 'AVAILABLE BOOKS IN DATABASE' list provided above. Explain why they are useful.\n" +
                "3. For each recommended book, mention its Title, Author, Category, and Shelf Number so the student can locate it.\n" +
                "4. Do NOT recommend or suggest any books that are not in the 'AVAILABLE BOOKS IN DATABASE' list. Do not make up or hallucinate any books.\n" +
                "5. If the student's request is for a book category or keyword that is not present in the list, politely inform them that we do not currently have books matching that topic in our inventory, and suggest they check other available categories.\n" +
                "6. If the student asks about library rules, timings, fines, or other policies, refer to the 'LIBRARY FAQ & POLICIES' section to provide an accurate answer.\n\n" +
                "Student's Question:\n" +
                "'" + question + "'";
    }

    private String callGeminiAPI(String promptText) {
        String url = String.format("%s/%s:generateContent?key=%s", apiUrl, modelName, apiKey);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);

        // Build the request body structure for Gemini API
        Map<String, Object> textPart = new HashMap<>();
        textPart.put("text", promptText);

        Map<String, Object> parts = new HashMap<>();
        parts.put("parts", Collections.singletonList(textPart));

        Map<String, Object> content = new HashMap<>();
        content.put("contents", Collections.singletonList(parts));

        HttpEntity<Map<String, Object>> requestEntity = new HttpEntity<>(content, headers);
        ResponseEntity<Map> responseEntity = restTemplate.postForEntity(url, requestEntity, Map.class);

        if (responseEntity.getStatusCode().is2xxSuccessful() && responseEntity.getBody() != null) {
            Map body = responseEntity.getBody();
            List candidates = (List) body.get("candidates");
            if (candidates != null && !candidates.isEmpty()) {
                Map candidate = (Map) candidates.get(0);
                Map contentMap = (Map) candidate.get("content");
                if (contentMap != null) {
                    List partsList = (List) contentMap.get("parts");
                    if (partsList != null && !partsList.isEmpty()) {
                        Map part = (Map) partsList.get(0);
                        String text = (String) part.get("text");
                        if (text != null) {
                            return text;
                        }
                    }
                }
            }
        }
        throw new RuntimeException("Failed to extract text response from Gemini API response structure");
    }

    private ChatResponseDTO buildOfflineResponse(String question, List<BookDTO> books) {
        StringBuilder response = new StringBuilder();
        response.append("👋 Hello! I am your Library Assistant. Currently, my advanced AI capabilities (Gemini API) are offline because no API key is configured.\n\n");
        
        if (books.isEmpty()) {
            response.append("Based on your query: \"").append(question).append("\", I couldn't find any matching available books in our catalog.\n\n")
                    .append("Please feel free to ask about library policies (e.g., timings, rules, borrow limits, fines) or check the main Book Catalog!");
        } else {
            response.append("However, I searched our library database and found ").append(books.size()).append(" matching available book(s):\n\n");
            for (BookDTO book : books) {
                response.append(String.format("📖 *%s* by %s\n", book.getTitle(), book.getAuthor()))
                        .append(String.format("   • Category: %s | Shelf Location: %s\n", book.getCategory(), book.getShelfNumber()))
                        .append(String.format("   • Description: %s\n\n", book.getDescription()));
            }
            response.append("You can locate these books on the shelves indicated above!");
        }

        return ChatResponseDTO.builder()
                .response(response.toString())
                .recommendedBooks(books)
                .build();
    }

    private ChatResponseDTO buildErrorResponse(String errorMsg, List<BookDTO> books) {
        StringBuilder response = new StringBuilder();
        response.append("⚠️ Hello! I encountered an error communicating with my AI service: ").append(errorMsg).append(".\n\n");
        
        if (books.isEmpty()) {
            response.append("I searched our database but could not find any matching books for your query.");
        } else {
            response.append("However, I successfully fetched the following matching available books directly from our inventory:\n\n");
            for (BookDTO book : books) {
                response.append(String.format("📖 *%s* by %s (Shelf: %s)\n", book.getTitle(), book.getAuthor(), book.getShelfNumber()));
            }
        }
        return ChatResponseDTO.builder()
                .response(response.toString())
                .recommendedBooks(books)
                .build();
    }

    private Set<String> extractKeywords(String question) {
        if (question == null || question.trim().isEmpty()) {
            return Collections.emptySet();
        }
        String[] words = question.toLowerCase()
                .replaceAll("[^a-zA-Z0-9\\s]", "")
                .split("\\s+");
Set<String> stopWords = new HashSet<>(Arrays.asList(
        //Set<String> stopWords = Set.of(
                "the", "a", "an", "and", "or", "but", "if", "then", "else", "when",
            "at", "by", "for", "with", "about", "against", "between", "into", "through",
            "during", "before", "after", "above", "below", "to", "from", "up", "down",
            "in", "out", "on", "off", "over", "under", "again", "further", "once",
            "here", "there", "where", "why", "how", "all", "any", "both", "each",
            "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only",
            "own", "same", "so", "than", "too", "very", "s", "t", "can", "will", "just",
            "don", "should", "now", "i", "me", "my", "myself", "we", "our", "ours",
            "ourselves", "you", "your", "yours", "yourself", "yourselves", "he", "him",
            "his", "himself", "she", "her", "hers", "herself", "it", "its", "itself",
            "they", "them", "their", "theirs", "themselves", "what", "which", "who",
            "whom", "this", "that", "these", "those", "am", "is", "are", "was", "were",
            "be", "been", "being", "have", "has", "had", "having", "do", "does", "did",
            "doing", "would", "could", "ought", "im", "youre", "hes", "shes",
            "theyre", "ive", "youve", "weve", "theyve", "id", "youd",
            "hed", "shed", "wed", "theyd", "ill", "youll", "hell", "shell", "well",
            "theyll", "cant", "cannot", "couldnt", "didnt", "doesnt", "dont", "hadnt",
            "hasnt", "havent", "isnt", "mustnt", "neednt", "shouldnt", "wasnt", "werent",
            "wont", "wouldnt", "recommend", "recommendation", "recommendations", "books",
            "book", "library", "assistant", "suggest", "suggestion", "suggestions", "find",
            "show", "please", "want", "like", "need", "list", "author", "writer", "written",
            "get", "search", "lookup"
        ));

        return Arrays.stream(words)
                .filter(w -> w.length() >= 3)
                .filter(w -> !stopWords.contains(w))
                .collect(Collectors.toSet());
    }

    private BookDTO convertToDTO(Book book) {
        return BookDTO.builder()
                .id(book.getId())
                .title(book.getTitle())
                .author(book.getAuthor())
                .category(book.getCategory())
                .description(book.getDescription())
                .publisher(book.getPublisher())
                .isbn(book.getIsbn())
                .shelfNumber(book.getShelfNumber())
                .quantity(book.getQuantity())
                .availability(book.getAvailability())
                .imageUrl(book.getImageUrl())
                .createdAt(book.getCreatedAt())
                .updatedAt(book.getUpdatedAt())
                .build();
    }
}
