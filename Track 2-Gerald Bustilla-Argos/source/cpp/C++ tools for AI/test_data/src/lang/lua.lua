local SearchEngine = {}
SearchEngine.__index = SearchEngine

function SearchEngine.new()
    local self = setmetatable({}, SearchEngine)
    self.index = {}
    return self
end

function SearchEngine:add(doc)
    table.insert(self.index, doc)
end
