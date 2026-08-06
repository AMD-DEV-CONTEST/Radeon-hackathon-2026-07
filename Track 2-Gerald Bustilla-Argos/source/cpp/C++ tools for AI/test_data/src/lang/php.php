<?php
class SearchController {
    public function search($query) {
        $results = $this->searchEngine->search($query);
        return json_encode($results);
    }
}
?>
