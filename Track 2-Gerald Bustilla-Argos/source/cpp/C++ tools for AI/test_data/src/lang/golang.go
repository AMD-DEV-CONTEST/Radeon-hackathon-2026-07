package main

import (
    "fmt"
    "net/http"
)

func searchHandler(w http.ResponseWriter, r *http.Request) {
    query := r.URL.Query().Get("query")
    fmt.Fprintf(w, "Search results for: %s", query)
}

func main() {
    http.HandleFunc("/search", searchHandler)
    http.ListenAndServe(":8080", nil)
}
