class SearchController < ApplicationController
  def search
    query = params[:query]
    results = SearchEngine.search(query)
    render json: results
  end
end
