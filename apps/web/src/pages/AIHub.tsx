import { useCallback, useEffect, useState } from 'react';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Bot, Search, Download, Heart, TrendingUp, Grid3X3, List, Zap, RefreshCw, Loader2 } from 'lucide-react';
import { publicJson } from '../lib/auth';

interface HubModel {
  repo_id: string;
  author: string;
  name: string;
  description: string;
  tags: string[];
  downloads: number;
  likes: number;
  created_at: string;
  updated_at: string;
  size: string;
  task_type: string;
  robot_type: string;
  compatible_skills: string[];
}

const sortOptions = [
  { value: 'downloads', label: 'Most Downloaded' },
  { value: 'likes', label: 'Most Liked' },
  { value: 'lastModified', label: 'Recently Updated' },
];

export function AIHub() {
  const [models, setModels] = useState<HubModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState('downloads');
  const [taskFilter, setTaskFilter] = useState('all');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');

  const loadModels = useCallback(async (query = '', sort = 'downloads') => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ tag: 'robotics', sort, limit: '30' });
      if (query) params.set('query', query);
      const data = await publicJson<{ total: number; items: HubModel[] }>(
        `/api/v1/hub/models?${params}`
      );
      setModels(data.items);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadModels(searchQuery, sortBy);
  }, [loadModels, sortBy]);

  const handleSearch = useCallback(() => {
    loadModels(searchQuery, sortBy);
  }, [loadModels, searchQuery, sortBy]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') handleSearch();
    },
    [handleSearch]
  );

  const taskTypes = ['all', ...new Set(models.map((m) => m.task_type).filter(Boolean))];

  const filteredModels = models.filter((model) => {
    if (taskFilter !== 'all' && model.task_type !== taskFilter) return false;
    return true;
  });

  const formatNumber = (num: number) => {
    if (num >= 1000) return `${(num / 1000).toFixed(1)}k`;
    return num.toString();
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">AI Hub</h1>
          <p className="text-muted-foreground mt-1">
            Discover robot learning models from HuggingFace and the community.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => loadModels(searchQuery, sortBy)} disabled={loading}>
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button variant="outline" onClick={() => (window.location.href = '/ai-hub/leaderboard')}>
            <TrendingUp className="h-4 w-4 mr-2" />
            Leaderboard
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="p-4 space-y-4">
          <div className="relative flex gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search models by name, tag, or description..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                className="pl-10"
              />
            </div>
            <Button onClick={handleSearch} disabled={loading}>
              Search
            </Button>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">Task:</span>
              <select
                value={taskFilter}
                onChange={(e) => setTaskFilter(e.target.value)}
                className="px-3 py-1.5 rounded-md border bg-background text-sm"
              >
                {taskTypes.map((type) => (
                  <option key={type} value={type}>
                    {type === 'all' ? 'All Tasks' : type}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">Sort:</span>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="px-3 py-1.5 rounded-md border bg-background text-sm"
              >
                {sortOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex-1" />

            <div className="flex items-center gap-1 border rounded-md p-1">
              <button
                onClick={() => setViewMode('grid')}
                className={`p-1.5 rounded ${viewMode === 'grid' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}
              >
                <Grid3X3 className="h-4 w-4" />
              </button>
              <button
                onClick={() => setViewMode('list')}
                className={`p-1.5 rounded ${viewMode === 'list' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}
              >
                <List className="h-4 w-4" />
              </button>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {loading ? 'Loading...' : `Showing ${filteredModels.length} models`}
        </p>
      </div>

      {error && (
        <div className="px-4 py-2 rounded-md bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
          {error}
        </div>
      )}

      {loading && models.length === 0 && (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      )}

      {viewMode === 'grid' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredModels.map((model) => (
            <Card
              key={model.repo_id}
              className="hover:border-primary/50 transition-all cursor-pointer group"
              onClick={() =>
                (window.location.href = `/ai-hub/model/${encodeURIComponent(model.repo_id)}`)
              }
            >
              <CardContent className="p-5">
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center text-lg">
                      <Bot className="h-5 w-5" />
                    </div>
                    <div>
                      <h3 className="font-semibold group-hover:text-primary transition-colors text-sm">
                        {model.name}
                      </h3>
                      <p className="text-xs text-muted-foreground">by {model.author}</p>
                    </div>
                  </div>
                </div>

                <p className="text-sm text-muted-foreground line-clamp-2 mb-4">
                  {model.description || 'No description available'}
                </p>

                <div className="flex flex-wrap gap-1.5 mb-4">
                  {model.compatible_skills.length > 0 &&
                    model.compatible_skills.slice(0, 2).map((s) => (
                      <Badge key={s} variant="outline" className="text-xs">
                        <Zap className="h-3 w-3 mr-1" />
                        {s}
                      </Badge>
                    ))}
                  {model.task_type && model.task_type !== 'unknown' && (
                    <Badge variant="secondary" className="text-xs">
                      {model.task_type}
                    </Badge>
                  )}
                  {model.tags.slice(0, 2).map((tag) => (
                    <Badge key={tag} variant="secondary" className="text-xs">
                      {tag}
                    </Badge>
                  ))}
                  {model.tags.length > 2 && (
                    <span className="text-xs text-muted-foreground">+{model.tags.length - 2}</span>
                  )}
                </div>

                <div className="flex items-center justify-between pt-3 border-t">
                  <div className="flex items-center gap-4 text-sm text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <Download className="h-3.5 w-3.5" />
                      {formatNumber(model.downloads)}
                    </span>
                    <span className="flex items-center gap-1">
                      <Heart className="h-3.5 w-3.5" />
                      {formatNumber(model.likes)}
                    </span>
                  </div>
                  {model.size && <span className="text-xs text-muted-foreground">{model.size}</span>}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {filteredModels.map((model) => (
            <Card
              key={model.repo_id}
              className="hover:border-primary/50 transition-all cursor-pointer"
              onClick={() =>
                (window.location.href = `/ai-hub/model/${encodeURIComponent(model.repo_id)}`)
              }
            >
              <CardContent className="p-4">
                <div className="flex items-center gap-4">
                  <div className="h-12 w-12 rounded-lg bg-primary/10 flex items-center justify-center text-xl">
                    <Bot className="h-5 w-5" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold">{model.name}</h3>
                    <p className="text-sm text-muted-foreground truncate">
                      {model.description || 'No description available'}
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                      {model.task_type && model.task_type !== 'unknown' && (
                        <Badge variant="secondary" className="text-xs">
                          {model.task_type}
                        </Badge>
                      )}
                      {model.tags.slice(0, 3).map((tag) => (
                        <Badge key={tag} variant="secondary" className="text-xs">
                          {tag}
                        </Badge>
                      ))}
                      <span className="text-xs text-muted-foreground">by {model.author}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-4 text-sm text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <Download className="h-4 w-4" />
                      {formatNumber(model.downloads)}
                    </span>
                    <span className="flex items-center gap-1">
                      <Heart className="h-4 w-4" />
                      {formatNumber(model.likes)}
                    </span>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {!loading && filteredModels.length === 0 && (
        <div className="text-center py-12">
          <Search className="h-10 w-10 mb-4 text-muted-foreground" />
          <h3 className="text-lg font-medium mb-2">No models found</h3>
          <p className="text-muted-foreground">Try adjusting your search or filters</p>
        </div>
      )}
    </div>
  );
}
