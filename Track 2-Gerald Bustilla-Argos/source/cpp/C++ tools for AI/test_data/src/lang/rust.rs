use std::collections::HashMap;

pub struct InvertedIndex {
    postings: HashMap<String, Vec<u32>>,
}

impl InvertedIndex {
    pub fn new() -> Self {
        InvertedIndex { postings: HashMap::new() }
    }

    pub fn add(&mut self, term: &str, doc_id: u32) {
        self.postings.entry(term.to_string()).or_insert_with(Vec::new).push(doc_id);
    }
}
