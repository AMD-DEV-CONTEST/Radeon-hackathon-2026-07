package main

import (
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

func main() {
	root := "/public"
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		path := filepath.Join(root, filepath.Clean("/"+r.URL.Path))
		if info, err := os.Stat(path); err == nil && !info.IsDir() {
			if strings.Contains(path, string(filepath.Separator)+"assets"+string(filepath.Separator)) {
				w.Header().Set("Cache-Control", "public, max-age=3600")
			}
			http.ServeFile(w, r, path)
			return
		}
		http.ServeFile(w, r, filepath.Join(root, "index.html"))
	})
	log.Println("Poster frontend listening on :80")
	log.Fatal(http.ListenAndServe(":80", nil))
}
